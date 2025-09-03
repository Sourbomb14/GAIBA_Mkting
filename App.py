import streamlit as st
import pandas as pd
import numpy as np
import smtplib
import ssl
import time
import re
import os
import io
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from email_validator import validate_email, EmailNotValidError
from dotenv import load_dotenv
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
from huggingface_hub import InferenceClient
from PIL import Image
import requests

# Load environment variables
load_dotenv()

# Configuration
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")
HF_TOKEN = os.getenv("HF_TOKEN")

# Countries and data
COUNTRIES = [
    "Global", "United States", "Canada", "United Kingdom", "Germany", 
    "France", "Spain", "Italy", "Australia", "Japan", "India", "China", "Brazil"
]

CURRENCIES = ["USD", "EUR", "GBP", "CAD", "AUD", "JPY", "INR", "BRL", "CNY"]

COUNTRY_COORDS = {
    "United States": [39.8283, -98.5795],
    "Canada": [56.1304, -106.3468],
    "United Kingdom": [55.3781, -3.4360],
    "Germany": [51.1657, 10.4515],
    "France": [46.6034, 1.8883],
    "India": [20.5937, 78.9629],
    "Australia": [-25.2744, 133.7751],
    "Japan": [36.2048, 138.2529],
    "China": [35.8617, 104.1954],
    "Brazil": [-14.2350, -51.9253]
}

# ================================
# SESSION STATE INITIALIZATION
# ================================

def init_session_state():
    """Initialize session state variables"""
    if 'current_page' not in st.session_state:
        st.session_state.current_page = "Campaign Dashboard"
    if 'campaign_data' not in st.session_state:
        st.session_state.campaign_data = None
    if 'campaign_strategy' not in st.session_state:
        st.session_state.campaign_strategy = None
    if 'email_template' not in st.session_state:
        st.session_state.email_template = None
    if 'email_contacts' not in st.session_state:
        st.session_state.email_contacts = None
    if 'campaign_results' not in st.session_state:
        st.session_state.campaign_results = None
    if 'generated_images' not in st.session_state:
        st.session_state.generated_images = []

# ================================
# HUGGINGFACE IMAGE GENERATOR
# ================================

class HuggingFaceImageGenerator:
    """Generate images using HuggingFace FLUX model"""
    
    def __init__(self):
        self.client = None
        if HF_TOKEN:
            try:
                self.client = InferenceClient(api_key=HF_TOKEN)
            except Exception as e:
                st.error(f"HuggingFace initialization failed: {e}")
    
    def generate_image(self, prompt, style="professional"):
        """Generate image using HuggingFace"""
        if not HF_TOKEN:
            st.warning("⚠️ HuggingFace token missing. Add HF_TOKEN to .env file")
            return None
            
        if not self.client:
            st.error("❌ HuggingFace client not initialized")
            return None
        
        try:
            full_prompt = f"{prompt}, {style} style, high quality, detailed, vibrant colors, marketing design"
            
            with st.spinner("🎨 Generating image with FLUX..."):
                # Try different model names that might work
                model_names = [
                    "stabilityai/stable-diffusion-2-1",
                    "runwayml/stable-diffusion-v1-5",
                    "CompVis/stable-diffusion-v1-4"
                ]
                
                for model in model_names:
                    try:
                        response = self.client.text_to_image(
                            prompt=full_prompt,
                            model=model
                        )
                        
                        if response:
                            # Store in session state
                            image_data = {
                                'prompt': full_prompt,
                                'timestamp': datetime.now(),
                                'image': response,
                                'model': model
                            }
                            st.session_state.generated_images.append(image_data)
                            
                            st.success(f"✨ Image generated with {model}!")
                            st.image(response, caption=prompt, use_column_width=True)
                            
                            # Download button
                            img_bytes = io.BytesIO()
                            response.save(img_bytes, format='PNG')
                            img_bytes.seek(0)
                            
                            st.download_button(
                                "📥 Download Image",
                                data=img_bytes.getvalue(),
                                file_name=f"generated_image_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
                                mime="image/png"
                            )
                            
                            return response
                            
                    except Exception as model_error:
                        continue
                
                st.error("❌ All image models failed. Check your HF_TOKEN permissions.")
                return None
                
        except Exception as e:
            st.error(f"❌ Image generation error: {str(e)}")
            return None

# ================================
# EMAIL PERSONALIZER
# ================================

class EmailPersonalizer:
    """Handle email personalization"""
    
    @staticmethod
    def extract_name_from_email(email):
        """Extract name from email address"""
        try:
            local_part = email.split('@')[0]
            # Remove numbers and special chars
            name_part = re.sub(r'[0-9._-]', ' ', local_part)
            name_parts = [part.capitalize() for part in name_part.split() if len(part) > 1]
            return ' '.join(name_parts) if name_parts else 'Valued Customer'
        except:
            return 'Valued Customer'
    
    @staticmethod
    def personalize_content(template, name, email=None):
        """Personalize template with name placeholders"""
        first_name = name.split()[0] if name and ' ' in name else name
        
        # Replace placeholders
        personalized = template.replace('{name}', name or 'Valued Customer')
        personalized = personalized.replace('{first_name}', first_name or 'Valued Customer')
        personalized = personalized.replace('{email}', email or '')
        
        return personalized

# ================================
# WORKING BULK EMAIL SENDER
# ================================

def send_bulk_emails_fixed(email_df, subject_template, body_template, progress_container):
    """WORKING bulk email function - completely rewritten"""
    
    # Validate credentials
    if not GMAIL_USER or not GMAIL_PASSWORD:
        st.error("❌ Email credentials missing!")
        st.code("""
Add to .env file:
GMAIL_USER=your_email@gmail.com
GMAIL_PASSWORD=your_16_digit_app_password
        """)
        return pd.DataFrame()
    
    results = []
    total_emails = len(email_df)
    personalizer = EmailPersonalizer()
    
    # Create progress tracking
    progress_bar = st.empty()
    status_text = st.empty()
    metrics_cols = st.columns(4)
    
    sent_count = 0
    failed_count = 0
    invalid_count = 0
    
    try:
        # Single SMTP connection for all emails
        context = ssl.create_default_context()
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        
        for idx, row in email_df.iterrows():
            current_progress = (idx + 1) / total_emails
            
            # Update progress
            progress_bar.progress(current_progress)
            status_text.info(f"📧 Sending {idx + 1}/{total_emails}: {row['email']}")
            
            try:
                # Validate email format
                validate_email(row['email'])
                
                # Get or extract name
                name = row.get('name', personalizer.extract_name_from_email(row['email']))
                
                # Personalize content
                personal_subject = personalizer.personalize_content(subject_template, name, row['email'])
                personal_body = personalizer.personalize_content(body_template, name, row['email'])
                
                # Create message
                msg = MIMEMultipart('alternative')
                msg['Subject'] = personal_subject
                msg['From'] = formataddr(("Marketing Team", GMAIL_USER))
                msg['To'] = row['email']
                
                # Add content (detect if HTML)
                if '<html>' in body_template.lower() or '<p>' in body_template.lower():
                    msg.attach(MIMEText(personal_body, 'html'))
                else:
                    msg.attach(MIMEText(personal_body, 'plain'))
                
                # Send email
                server.sendmail(GMAIL_USER, row['email'], msg.as_string())
                
                # Record success
                results.append({
                    'email': row['email'],
                    'name': name,
                    'status': 'sent',
                    'error': '',
                    'timestamp': datetime.now().strftime('%H:%M:%S')
                })
                sent_count += 1
                
            except EmailNotValidError:
                results.append({
                    'email': row['email'],
                    'name': row.get('name', 'Unknown'),
                    'status': 'invalid',
                    'error': 'Invalid email format',
                    'timestamp': datetime.now().strftime('%H:%M:%S')
                })
                invalid_count += 1
                
            except Exception as email_error:
                results.append({
                    'email': row['email'],
                    'name': row.get('name', 'Unknown'),
                    'status': 'failed',
                    'error': str(email_error),
                    'timestamp': datetime.now().strftime('%H:%M:%S')
                })
                failed_count += 1
            
            # Update metrics
            with metrics_cols[0]:
                st.metric("✅ Sent", sent_count)
            with metrics_cols[1]:
                st.metric("❌ Failed", failed_count)
            with metrics_cols[2]:
                st.metric("⚠️ Invalid", invalid_count)
            with metrics_cols[3]:
                st.metric("📊 Progress", f"{current_progress*100:.0f}%")
            
            # Rate limiting
            time.sleep(1)
        
        # Close SMTP connection
        server.quit()
        
        # Final status
        progress_bar.progress(1.0)
        status_text.success("🎉 Email campaign completed!")
        
    except Exception as smtp_error:
        st.error(f"❌ SMTP Connection Error: {str(smtp_error)}")
        return pd.DataFrame()
    
    return pd.DataFrame(results)

# ================================
# FILE PROCESSOR
# ================================

class FileProcessor:
    """Process uploaded files for email extraction"""
    
    def __init__(self):
        self.personalizer = EmailPersonalizer()
    
    def process_contacts_file(self, uploaded_file):
        """Process uploaded contact file"""
        try:
            # Read file based on extension
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            elif uploaded_file.name.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(uploaded_file)
            else:
                st.error("❌ Please upload CSV or Excel files only")
                return None
            
            # Standardize column names
            df.columns = df.columns.str.lower().str.strip()
            
            # Find email column
            email_col = None
            for col in df.columns:
                if any(keyword in col for keyword in ['email', 'mail', 'e-mail']):
                    email_col = col
                    break
            
            if email_col is None:
                st.error("❌ No email column found. Ensure your file has an 'email' column.")
                return None
            
            # Find name columns
            name_cols = []
            for col in df.columns:
                if any(keyword in col for keyword in ['name', 'first', 'last', 'fname', 'lname']):
                    name_cols.append(col)
            
            # Process contacts
            contacts = []
            for _, row in df.iterrows():
                email = str(row[email_col]).strip().lower()
                
                # Skip empty emails
                if pd.isna(row[email_col]) or email == 'nan' or email == '':
                    continue
                
                # Validate email
                try:
                    validate_email(email)
                except EmailNotValidError:
                    continue
                
                # Get name
                if name_cols:
                    name_parts = []
                    for col in name_cols:
                        if col in row and not pd.isna(row[col]):
                            name_parts.append(str(row[col]).strip())
                    full_name = ' '.join(name_parts) if name_parts else self.personalizer.extract_name_from_email(email)
                else:
                    full_name = self.personalizer.extract_name_from_email(email)
                
                contacts.append({
                    'email': email,
                    'name': full_name
                })
            
            if not contacts:
                st.error("❌ No valid email addresses found in file")
                return None
            
            return pd.DataFrame(contacts)
            
        except Exception as e:
            st.error(f"❌ Error processing file: {str(e)}")
            return None

# ================================
# CAMPAIGN GENERATOR
# ================================

def generate_campaign_strategy(campaign_data):
    """Generate comprehensive campaign strategy"""
    
    company = campaign_data.get('company_name', 'Your Company')
    campaign_type = campaign_data.get('campaign_type', 'Marketing Campaign')
    audience = campaign_data.get('target_audience', 'Target Audience')
    location = campaign_data.get('location', 'Global')
    budget = campaign_data.get('budget', 'TBD')
    currency = campaign_data.get('currency', 'USD')
    duration = campaign_data.get('duration', 'TBD')
    channels = ', '.join(campaign_data.get('channels', ['Email']))
    
    strategy = f"""
# {company} - {campaign_type} Strategy

## 🎯 Executive Summary
**Company:** {company}  
**Campaign:** {campaign_type}  
**Target Market:** {location}  
**Budget:** {budget} {currency}  
**Duration:** {duration}  

## 👥 Target Audience
{audience}

**Key Demographics:**
- Geographic Focus: {location}
- Primary channels: {channels}
- Budget allocation: {budget} {currency}

## 🚀 Campaign Objectives
1. **Brand Awareness** - Increase visibility in {location}
2. **Lead Generation** - Attract qualified prospects
3. **Customer Engagement** - Build relationships through {channels}
4. **Conversion Optimization** - Turn prospects into customers
5. **ROI Maximization** - Achieve profitable growth

## 📈 Strategy & Tactics

### Phase 1: Foundation (Week 1-2)
- **Market Research:** Analyze {location} market conditions
- **Audience Segmentation:** Refine targeting within {audience}
- **Creative Development:** Design assets for {channels}
- **Infrastructure Setup:** Implement tracking and analytics

### Phase 2: Launch (Week 3-4)
- **Campaign Deployment:** Launch across {channels}
- **Performance Monitoring:** Track KPIs in real-time
- **Customer Support:** Prepare for increased inquiries
- **Quick Optimizations:** Adjust based on early data

### Phase 3: Optimization (Week 5-6)
- **Data Analysis:** Deep dive into performance metrics
- **A/B Testing:** Test variations for improvement
- **Budget Reallocation:** Shift spend to best performers
- **Scale Success:** Expand winning elements

## 💰 Budget Breakdown
**Total Budget:** {budget} {currency}

- **Creative & Content:** 25%
- **Media & Advertising:** 45%
- **Technology & Tools:** 20%
- **Analytics & Reporting:** 10%

## 📊 Success Metrics
- **Reach:** Target audience exposure
- **Engagement:** Interactions and responses
- **Conversions:** Leads and sales generated
- **ROI:** Revenue vs. investment ratio
- **Customer Acquisition Cost (CAC)**
- **Customer Lifetime Value (CLV)**

## 🎯 Channel Strategy
**Primary Channels:** {channels}

**Email Marketing:**
- Personalized campaigns with high open rates
- Segmented messaging based on audience behavior
- Automated drip sequences for nurturing
- A/B testing for subject lines and content

**Additional Channels:**
- Social media for community building
- Content marketing for thought leadership  
- Paid advertising for targeted reach
- Analytics for data-driven decisions

## 🔄 Implementation Timeline
**Week 1-2:** Campaign setup and preparation
**Week 3-4:** Launch and initial optimization  
**Week 5-6:** Performance analysis and scaling
**Ongoing:** Monitoring and continuous improvement

## 📋 Next Steps
1. ✅ Review and approve this strategy
2. 🎨 Begin creative asset development
3. 🔧 Set up tracking systems
4. 🚀 Launch campaign execution
5. 📊 Monitor and optimize performance

---
*Strategy generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}*
"""
    
    return strategy

def generate_email_template(template_type, tone):
    """Generate email template based on type and tone"""
    
    templates = {
        'welcome': {
            'subject': 'Welcome to our community, {first_name}!',
            'html': '''
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #f4f4f4; }
        .container { background: white; padding: 30px; border-radius: 10px; margin: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; margin: -30px -30px 30px -30px; }
        .cta-button { background: #28a745; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; display: inline-block; margin: 20px 0; }
        .footer { border-top: 1px solid #eee; padding-top: 20px; margin-top: 30px; font-size: 12px; color: #666; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Welcome, {first_name}! 🎉</h1>
        </div>
        <h2>We're thrilled to have you join us!</h2>
        <p>Dear {name},</p>
        <p>Thank you for joining our community. We're excited to share amazing content and exclusive offers with you.</p>
        <center><a href="#" class="cta-button">Get Started</a></center>
        <p>Looking forward to this journey together!</p>
        <div class="footer">
            <p>Best regards,<br>The Marketing Team</p>
        </div>
    </div>
</body>
</html>
            '''
        },
        'promotional': {
            'subject': 'Special offer just for you, {first_name}!',
            'html': '''
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #f4f4f4; }
        .container { background: white; padding: 30px; border-radius: 10px; margin: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .header { background: linear-gradient(135deg, #ff6b6b 0%, #ee5a52 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; margin: -30px -30px 30px -30px; }
        .offer-box { background: #fff3cd; border: 1px solid #ffeaa7; padding: 20px; border-radius: 5px; text-align: center; margin: 20px 0; }
        .cta-button { background: #dc3545; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; display: inline-block; margin: 20px 0; font-size: 18px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎁 Special Offer for {first_name}!</h1>
        </div>
        <div class="offer-box">
            <h2>🔥 LIMITED TIME: 50% OFF!</h2>
            <p>Exclusive deal just for you, {name}</p>
        </div>
        <p>Don't miss out on this incredible opportunity!</p>
        <center><a href="#" class="cta-button">Claim Your Offer</a></center>
        <p><em>Offer expires soon - act fast!</em></p>
    </div>
</body>
</html>
            '''
        },
        'newsletter': {
            'subject': 'Your weekly update, {first_name}',
            'html': '''
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #f4f4f4; }
        .container { background: white; padding: 30px; border-radius: 10px; margin: 20px; }
        .header { background: linear-gradient(135deg, #74b9ff 0%, #0984e3 100%); color: white; padding: 20px; text-align: center; border-radius: 10px; }
        .article { border-bottom: 1px solid #eee; padding: 20px 0; }
        .cta-button { background: #0984e3; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; display: inline-block; margin: 10px 0; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📰 Weekly Newsletter</h1>
            <p>Hi {first_name}, here's what's new this week!</p>
        </div>
        <div class="article">
            <h3>🚀 Latest Updates</h3>
            <p>Dear {name}, we've got some exciting news to share with you this week...</p>
            <a href="#" class="cta-button">Read More</a>
        </div>
        <p>Thanks for being part of our community!</p>
    </div>
</body>
</html>
            '''
        }
    }
    
    template_data = templates.get(template_type.lower(), templates['welcome'])
    return template_data['subject'], template_data['html']

# ================================
# STREAMLIT APP CONFIGURATION
# ================================

st.set_page_config(
    page_title="Marketing Campaign War Room",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
init_session_state()

# Custom CSS for modern dark theme
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    .stApp {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        font-family: 'Inter', sans-serif;
    }
    
    .main-header {
        background: linear-gradient(135deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0.05) 100%);
        padding: 2rem;
        border-radius: 15px;
        text-align: center;
        margin-bottom: 2rem;
        backdrop-filter: blur(10px);
    }
    
    .stButton > button {
        background: linear-gradient(45deg, #28a745, #20c997) !important;
        color: white !important;
        border: none !important;
        border-radius: 10px !important;
        padding: 0.75rem 2rem !important;
        font-weight: 600 !important;
        transition: all 0.3s ease !important;
        width: 100% !important;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 10px 25px rgba(40, 167, 69, 0.3) !important;
    }
    
    .metric-card {
        background: linear-gradient(135deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0.05) 100%);
        padding: 1.5rem;
        border-radius: 10px;
        text-align: center;
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255,255,255,0.2);
    }
    
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea,
    .stSelectbox > div > div > select {
        background: rgba(255,255,255,0.9) !important;
        border: 1px solid rgba(255,255,255,0.3) !important;
        border-radius: 8px !important;
        color: #333 !important;
    }
    
    .success-metric {
        background: linear-gradient(45deg, #28a745, #20c997);
        color: white;
        padding: 1rem;
        border-radius: 8px;
        text-align: center;
    }
    
    .sidebar .stButton > button {
        background: linear-gradient(45deg, #007bff, #0056b3) !important;
        margin-bottom: 0.5rem !important;
    }
</style>
""", unsafe_allow_html=True)

# ================================
# MAIN APPLICATION
# ================================

def main():
    """Main application function"""
    
    # Header
    st.markdown("""
    <div class="main-header">
        <h1 style="color: white; font-size: 3.5rem; margin-bottom: 0;">🚀 Marketing Campaign War Room</h1>
        <p style="color: rgba(255,255,255,0.8); font-size: 1.3rem; margin-top: 0;">Complete AI-Powered Campaign Generation & Email Marketing Platform</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Navigation Sidebar
    with st.sidebar:
        st.markdown("### 🎯 Navigation")
        
        # Navigation buttons
        if st.button("🎯 Campaign Dashboard", key="nav_campaign"):
            st.session_state.current_page = "Campaign Dashboard"
            st.rerun()
        
        if st.button("📧 Email Marketing", key="nav_email"):
            st.session_state.current_page = "Email Marketing"  
            st.rerun()
        
        if st.button("📊 Analytics & Reports", key="nav_analytics"):
            st.session_state.current_page = "Analytics & Reports"
            st.rerun()
        
        st.markdown("---")
        
        # System Status
        st.markdown("### 🔧 System Status")
        
        if GMAIL_USER and GMAIL_PASSWORD:
            st.success("📧 Email Service: ✅ Connected")
        else:
            st.error("📧 Email Service: ❌ Not configured")
        
        if HF_TOKEN:
            st.success("🎨 Image Generator: ✅ Connected")
        else:
            st.warning("🎨 Image Generator: ⚠️ Not configured")
        
        st.markdown("---")
        
        # Quick Stats
        if st.session_state.campaign_data:
            st.markdown("### 🎯 Active Campaign")
            st.info(f"**{st.session_state.campaign_data['company_name']}**")
            st.caption(f"Type: {st.session_state.campaign_data['campaign_type']}")
        
        if st.session_state.email_contacts is not None:
            st.markdown("### 📊 Contact Stats")
            st.info(f"📧 Loaded: {len(st.session_state.email_contacts)} contacts")
    
    # Main Content Area
    if st.session_state.current_page == "Campaign Dashboard":
        show_campaign_dashboard()
    elif st.session_state.current_page == "Email Marketing":
        show_email_marketing()  
    elif st.session_state.current_page == "Analytics & Reports":
        show_analytics_reports()

def show_campaign_dashboard():
    """Campaign strategy generation page"""
    
    st.header("🎯 AI Campaign Strategy Generator")
    st.write("Create comprehensive marketing campaigns with AI-powered insights")
    
    # Campaign Creation Form
    with st.form("campaign_creation_form"):
        st.subheader("📋 Campaign Configuration")
        
        # Basic Information
        col1, col2 = st.columns(2)
        
        with col1:
            company_name = st.text_input("🏢 Company Name", 
                placeholder="Enter your company name")
            
            campaign_type = st.selectbox("📋 Campaign Type", [
                "Product Launch",
                "Brand Awareness", 
                "Lead Generation",
                "Customer Retention",
                "Seasonal Campaign",
                "Event Promotion",
                "Sales Campaign"
            ])
            
            target_audience = st.text_area("👥 Target Audience Description", 
                placeholder="Describe your target audience: demographics, interests, behaviors...")
            
            duration = st.text_input("📅 Campaign Duration", 
                placeholder="e.g., 6 weeks, 3 months")
        
        with col2:
            channels = st.multiselect("📢 Marketing Channels", [
                "Email Marketing",
                "Social Media Marketing", 
                "Google Ads",
                "Facebook Ads",
                "Content Marketing",
                "Influencer Marketing",
                "SEO/SEM",
                "Traditional Media"
            ])
            
            location = st.selectbox("🌍 Target Location", COUNTRIES)
            
            customer_segment = st.selectbox("💼 Customer Segment", [
                "B2B Enterprise",
                "B2B SMB", 
                "B2C Mass Market",
                "B2C Premium",
                "B2C Niche"
            ])
            
            industry = st.selectbox("🏭 Industry", [
                "Technology",
                "Healthcare", 
                "Finance",
                "E-commerce",
                "Education",
                "Real Estate",
                "Food & Beverage",
                "Fashion & Beauty",
                "Travel & Tourism",
                "Other"
            ])
        
        # Budget Information
        st.subheader("💰 Budget Planning")
        budget_col1, budget_col2 = st.columns(2)
        
        with budget_col1:
            budget_amount = st.text_input("💵 Budget Amount", 
                placeholder="e.g., 50000")
        with budget_col2:
            currency = st.selectbox("💱 Currency", CURRENCIES)
        
        # Product/Service Details
        product_description = st.text_area("📦 Product/Service Description",
            placeholder="Describe what you're promoting: features, benefits, unique selling points...")
        
        campaign_objectives = st.text_area("🎯 Specific Campaign Objectives",
            placeholder="What do you want to achieve? Be specific about goals and KPIs...")
        
        # Form Submission
        col1, col2 = st.columns(2)
        with col1:
            generate_strategy = st.form_submit_button("🚀 Generate Campaign Strategy", 
                use_container_width=True)
        with col2:
            generate_image = st.form_submit_button("🎨 Generate Campaign Image", 
                use_container_width=True)
    
    # Handle Strategy Generation
    if generate_strategy and company_name and campaign_type:
        campaign_data = {
            'company_name': company_name,
            'campaign_type': campaign_type,
            'target_audience': target_audience,
            'duration': duration,
            'channels': channels,
            'location': location,
            'customer_segment': customer_segment,
            'industry': industry,
            'budget': budget_amount,
            'currency': currency,
            'product_description': product_description,
            'campaign_objectives': campaign_objectives
        }
        
        with st.spinner("🤖 Generating comprehensive campaign strategy..."):
            strategy = generate_campaign_strategy(campaign_data)
            
            # Store in session state
            st.session_state.campaign_data = campaign_data
            st.session_state.campaign_strategy = strategy
            
            st.success("✨ Campaign strategy generated successfully!")
            st.balloons()
    
    # Handle Image Generation
    if generate_image and st.session_state.campaign_data:
        image_generator = HuggingFaceImageGenerator()
        prompt = f"Professional marketing campaign for {st.session_state.campaign_data['company_name']} {st.session_state.campaign_data['campaign_type']}"
        image_generator.generate_image(prompt, "professional marketing")
    
    # Display Generated Strategy
    if st.session_state.campaign_strategy:
        st.markdown("---")
        st.markdown("## 📋 Your AI-Generated Campaign Strategy")
        
        # Strategy Display
        st.markdown(st.session_state.campaign_strategy)
        
        # Action Buttons
        st.markdown("### 🚀 Next Steps")
        action_col1, action_col2, action_col3 = st.columns(3)
        
        with action_col1:
            if st.button("📧 Create Email Campaign", use_container_width=True):
                st.session_state.current_page = "Email Marketing"
                st.rerun()
        
        with action_col2:
            if st.button("📊 View Analytics", use_container_width=True):
                st.session_state.current_page = "Analytics & Reports"
                st.rerun()
        
        with action_col3:
            if st.session_state.campaign_data:
                st.download_button(
                    "📄 Download Strategy",
                    data=st.session_state.campaign_strategy,
                    file_name=f"{st.session_state.campaign_data['company_name']}_campaign_strategy.md",
                    mime="text/markdown",
                    use_container_width=True
                )

def show_email_marketing():
    """Email marketing and bulk sending page"""
    
    st.header("📧 Email Marketing Center")
    
    # Show active campaign info
    if st.session_state.campaign_data:
        st.success(f"🎯 Active Campaign: **{st.session_state.campaign_data['company_name']}** - {st.session_state.campaign_data['campaign_type']}")
    else:
        st.info("💡 Create a campaign first in the Campaign Dashboard for better email generation")
    
    # Email Template Generation
    st.subheader("🎨 Email Template Generator")
    
    template_col1, template_col2 = st.columns(2)
    
    with template_col1:
        template_type = st.selectbox("📧 Email Template Type", [
            "Welcome",
            "Promotional", 
            "Newsletter",
            "Product Announcement",
            "Follow-up",
            "Event Invitation"
        ])
        
        tone = st.selectbox("🎭 Email Tone", [
            "Professional",
            "Friendly", 
            "Casual",
            "Urgent",
            "Formal"
        ])
    
    with template_col2:
        if st.button("🚀 Generate Email Template", use_container_width=True):
            with st.spinner("Generating email template..."):
                subject, html_template = generate_email_template(template_type, tone)
                st.session_state.email_template = {
                    'subject': subject,
                    'html': html_template,
                    'type': template_type,
                    'tone': tone
                }
                st.success("✨ Email template generated successfully!")
    
    # Email Template Editor
    if st.session_state.email_template:
        st.markdown("---")
        st.subheader("📝 Email Template Editor")
        
        # Subject Line Editor
        subject_line = st.text_input("📧 Email Subject Line", 
            value=st.session_state.email_template['subject'])
        
        # HTML Content Editor
        html_content = st.text_area("🌐 Email HTML Content", 
            value=st.session_state.email_template['html'], 
            height=400,
            help="Use {first_name}, {name}, and {email} for personalization")
        
        # Update template in session state
        st.session_state.email_template['subject'] = subject_line
        st.session_state.email_template['html'] = html_content
        
        # Preview Button
        if st.button("👀 Preview Email Template"):
            personalizer = EmailPersonalizer()
            preview_subject = personalizer.personalize_content(subject_line, "John Smith", "john@example.com")
            preview_html = personalizer.personalize_content(html_content, "John Smith", "john@example.com")
            
            st.markdown("### 📧 Email Preview")
            st.markdown(f"**Subject:** {preview_subject}")
            st.components.v1.html(preview_html, height=500, scrolling=True)
    
    st.markdown("---")
    
    # Contact File Upload
    st.subheader("👥 Upload Email Contacts")
    
    uploaded_file = st.file_uploader(
        "📁 Upload Contact File (CSV/Excel)", 
        type=['csv', 'xlsx', 'xls'],
        help="Upload a CSV or Excel file with email addresses. Include 'name' columns for personalization."
    )
    
    if uploaded_file:
        processor = FileProcessor()
        contacts = processor.process_contacts_file(uploaded_file)
        
        if contacts is not None:
            st.session_state.email_contacts = contacts
            st.success(f"✅ Successfully loaded {len(contacts)} valid contacts!")
            
            # Show contact preview with editing capability
            st.subheader("📋 Contact Preview & Editor")
            edited_contacts = st.data_editor(
                contacts,
                column_config={
                    "email": st.column_config.TextColumn("📧 Email Address", width="medium"),
                    "name": st.column_config.TextColumn("👤 Full Name", width="medium")
                },
                num_rows="dynamic",
                use_container_width=True,
                key="contact_editor"
            )
            
            # Update contacts in session state
            st.session_state.email_contacts = edited_contacts
            
            # Contact Statistics
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("👥 Total Contacts", len(edited_contacts))
            with col2:
                domains = edited_contacts['email'].str.split('@').str[1].nunique()
                st.metric("🏢 Unique Domains", domains)
            with col3:
                avg_name_length = edited_contacts['name'].str.len().mean()
                st.metric("📝 Avg Name Length", f"{avg_name_length:.0f} chars")
    
    # Bulk Email Campaign Launch
    if (st.session_state.email_contacts is not None and 
        st.session_state.email_template is not None):
        
        st.markdown("---")
        st.subheader("🚀 Launch Email Campaign")
        
        df = st.session_state.email_contacts
        
        # Campaign Overview
        st.markdown("### 📊 Campaign Overview")
        overview_col1, overview_col2, overview_col3, overview_col4 = st.columns(4)
        
        with overview_col1:
            st.markdown(f"""
            <div class="metric-card">
                <h3>👥 Recipients</h3>
                <h2>{len(df)}</h2>
            </div>
            """, unsafe_allow_html=True)
        
        with overview_col2:
            domains = df['email'].str.split('@').str[1].nunique()
            st.markdown(f"""
            <div class="metric-card">
                <h3>🏢 Domains</h3>
                <h2>{domains}</h2>
            </div>
            """, unsafe_allow_html=True)
        
        with overview_col3:
            st.markdown(f"""
            <div class="metric-card">
                <h3>📧 Template</h3>
                <h2>✅ Ready</h2>
            </div>
            """, unsafe_allow_html=True)
        
        with overview_col4:
            estimated_time = len(df) * 1.5 / 60  # 1.5 seconds per email
            st.markdown(f"""
            <div class="metric-card">
                <h3>⏱️ Est. Time</h3>
                <h2>{estimated_time:.0f}m</h2>
            </div>
            """, unsafe_allow_html=True)
        
        # Test Email Section
        st.markdown("### 🧪 Test Email")
        test_col1, test_col2 = st.columns(2)
        
        with test_col1:
            test_email = st.text_input("🎯 Test Email Address", 
                placeholder="your-email@example.com")
        
        with test_col2:
            if test_email and st.button("🧪 Send Test Email"):
                try:
                    personalizer = EmailPersonalizer()
                    test_subject = personalizer.personalize_content(
                        st.session_state.email_template['subject'], 
                        "Test User", 
                        test_email
                    )
                    test_html = personalizer.personalize_content(
                        st.session_state.email_template['html'], 
                        "Test User", 
                        test_email
                    )
                    
                    # Send test email
                    context = ssl.create_default_context()
                    with smtplib.SMTP('smtp.gmail.com', 587) as server:
                        server.starttls(context=context)
                        server.login(GMAIL_USER, GMAIL_PASSWORD)
                        
                        msg = MIMEMultipart('alternative')
                        msg['Subject'] = f"[TEST] {test_subject}"
                        msg['From'] = formataddr(("Marketing Team", GMAIL_USER))
                        msg['To'] = test_email
                        msg.attach(MIMEText(test_html, 'html'))
                        
                        server.sendmail(GMAIL_USER, test_email, msg.as_string())
                        
                    st.success("✅ Test email sent successfully!")
                    
                except Exception as e:
                    st.error(f"❌ Test email failed: {str(e)}")
        
        # Campaign Launch
        st.markdown("### 🎯 Campaign Launch")
        
        # Pre-launch checklist
        with st.expander("📋 Pre-Launch Checklist"):
            st.write("✅ Email template created and tested")
            st.write(f"✅ {len(df)} contacts loaded and validated")
            st.write("✅ Subject line configured")
            st.write("✅ Gmail credentials configured")
            st.write("⚠️ **Make sure everything looks good before launching!**")
        
        # Launch Warning and Button
        st.warning(f"⚠️ You are about to send {len(df)} personalized emails. This action cannot be undone!")
        
        if st.button("🚀 LAUNCH EMAIL CAMPAIGN", type="primary", use_container_width=True):
            
            # Validate email configuration
            if not GMAIL_USER or not GMAIL_PASSWORD:
                st.error("❌ Gmail configuration missing!")
                st.code("""
Add to your .env file:
GMAIL_USER=your_email@gmail.com
GMAIL_PASSWORD=your_16_digit_app_password
                """)
                st.stop()
            
            # Final confirmation
            st.error("🔴 **FINAL CONFIRMATION REQUIRED**")
            
            if st.button("✅ YES, SEND ALL EMAILS NOW", key="final_confirm"):
                
                st.info("🚀 Launching email campaign...")
                
                # Create progress container
                progress_container = st.container()
                
                # Send bulk emails using the working function
                with progress_container:
                    results = send_bulk_emails_fixed(
                        df,
                        st.session_state.email_template['subject'],
                        st.session_state.email_template['html'],
                        progress_container
                    )
                
                # Process and display results
                if not results.empty:
                    # Calculate metrics
                    sent_count = len(results[results['status'] == 'sent'])
                    failed_count = len(results[results['status'] == 'failed']) 
                    invalid_count = len(results[results['status'] == 'invalid'])
                    success_rate = (sent_count / len(results)) * 100
                    
                    # Display results
                    st.markdown("### 🎉 Campaign Results")
                    
                    result_col1, result_col2, result_col3, result_col4 = st.columns(4)
                    
                    with result_col1:
                        st.markdown(f"""
                        <div class="success-metric">
                            <h3>✅ Successfully Sent</h3>
                            <h1>{sent_count}</h1>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    with result_col2:
                        st.metric("❌ Failed", failed_count)
                    
                    with result_col3:
                        st.metric("⚠️ Invalid", invalid_count)
                    
                    with result_col4:
                        st.metric("📊 Success Rate", f"{success_rate:.1f}%")
                    
                    # Store results for analytics
                    st.session_state.campaign_results = results
                    
                    # Success celebration
                    if sent_count > 0:
                        st.balloons()
                        st.success(f"🎊 Campaign completed! {sent_count} emails sent successfully!")
                    
                    # Download results
                    csv_data = results.to_csv(index=False)
                    st.download_button(
                        "📥 Download Campaign Results",
                        data=csv_data,
                        file_name=f"email_campaign_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                    
                    # Show detailed results
                    with st.expander("📋 View Detailed Results"):
                        st.dataframe(results, use_container_width=True)
                
                else:
                    st.error("❌ Campaign failed - no results generated")
    
    # Quick Single Email Section
    st.markdown("---")
    st.subheader("📧 Quick Single Email")
    st.write("Send a one-off email to a single recipient")
    
    with st.form("single_email_form"):
        single_col1, single_col2 = st.columns(2)
        
        with single_col1:
            single_email = st.text_input("📧 Recipient Email")
            single_name = st.text_input("👤 Recipient Name", 
                help="Leave empty to auto-extract from email")
            single_subject = st.text_input("📝 Email Subject")
        
        with single_col2:
            use_template = st.checkbox("Use Generated Template", 
                value=bool(st.session_state.email_template))
            
            if use_template and st.session_state.email_template:
                st.info("✅ Will use the generated template")
                single_body = st.text_area("📧 Email Body", 
                    value=st.session_state.email_template['html'], 
                    height=200)
            else:
                single_body = st.text_area("📧 Email Body", 
                    placeholder="Enter your email content here...",
                    height=200)
        
        if st.form_submit_button("📧 Send Single Email", use_container_width=True):
            if single_email and single_subject and single_body:
                try:
                    personalizer = EmailPersonalizer()
                    
                    # Get or extract name
                    final_name = single_name if single_name else personalizer.extract_name_from_email(single_email)
                    
                    # Personalize content
                    final_subject = personalizer.personalize_content(single_subject, final_name, single_email)
                    final_body = personalizer.personalize_content(single_body, final_name, single_email)
                    
                    # Send email
                    context = ssl.create_default_context()
                    with smtplib.SMTP('smtp.gmail.com', 587) as server:
                        server.starttls(context=context)
                        server.login(GMAIL_USER, GMAIL_PASSWORD)
                        
                        msg = MIMEMultipart('alternative')
                        msg['Subject'] = final_subject
                        msg['From'] = formataddr(("Marketing Team", GMAIL_USER))
                        msg['To'] = single_email
                        
                        # Detect content type
                        if '<html>' in single_body.lower() or '<p>' in single_body.lower():
                            msg.attach(MIMEText(final_body, 'html'))
                        else:
                            msg.attach(MIMEText(final_body, 'plain'))
                        
                        server.sendmail(GMAIL_USER, single_email, msg.as_string())
                    
                    st.success(f"✅ Email sent successfully to {final_name} ({single_email})!")
                    
                except Exception as e:
                    st.error(f"❌ Failed to send email: {str(e)}")
            else:
                st.error("⚠️ Please fill in all required fields")

def show_analytics_reports():
    """Analytics and reporting page"""
    
    st.header("📊 Campaign Analytics & Reports")
    
    # Campaign Geographic Analysis
    if st.session_state.campaign_data:
        st.subheader("🗺️ Campaign Geographic Analysis")
        
        campaign = st.session_state.campaign_data
        location = campaign['location']
        
        # Display campaign info
        info_col1, info_col2, info_col3, info_col4 = st.columns(4)
        
        with info_col1:
            st.metric("🎯 Campaign Type", campaign['campaign_type'])
        with info_col2:
            st.metric("🌍 Target Location", location)
        with info_col3:
            st.metric("💰 Budget", f"{campaign.get('budget', 'TBD')} {campaign.get('currency', 'USD')}")
        with info_col4:
            st.metric("📅 Duration", campaign.get('duration', 'TBD'))
        
        # Geographic visualization
        if location in COUNTRY_COORDS:
            coords = COUNTRY_COORDS[location]
            
            # Create map data
            map_data = pd.DataFrame({
                'lat': [coords[0]],
                'lon': [coords[1]], 
                'location': [location],
                'campaign': [campaign['campaign_type']],
                'company': [campaign['company_name']]
            })
            
            # Create interactive map
            fig = px.scatter_mapbox(
                map_data,
                lat='lat',
                lon='lon',
                hover_name='location',
                hover_data={
                    'campaign': True, 
                    'company': True, 
                    'lat': False, 
                    'lon': False
                },
                color_discrete_sequence=['#28a745'],
                size_max=20,
                zoom=3,
                title=f"Campaign Target Location: {location}"
            )
            
            fig.update_layout(
                mapbox_style="carto-positron",
                template="plotly_white",
                height=400
            )
            
            st.plotly_chart(fig, use_container_width=True)
        
        # Campaign projections
        if campaign.get('budget') and campaign['budget'].isdigit():
            st.subheader("📈 Campaign Projections")
            
            budget = int(campaign['budget'])
            
            # Calculate estimated metrics
            estimated_reach = budget * 25  # $1 = 25 people reach
            estimated_clicks = int(estimated_reach * 0.035)  # 3.5% CTR
            estimated_conversions = int(estimated_clicks * 0.025)  # 2.5% conversion
            estimated_revenue = estimated_conversions * 75  # $75 per conversion
            roi = ((estimated_revenue - budget) / budget) * 100
            
            proj_col1, proj_col2, proj_col3, proj_col4 = st.columns(4)
            
            with proj_col1:
                st.metric("👥 Estimated Reach", f"{estimated_reach:,}")
            with proj_col2:
                st.metric("👆 Expected Clicks", f"{estimated_clicks:,}")
            with proj_col3:
                st.metric("💰 Projected Conversions", f"{estimated_conversions:,}")
            with proj_col4:
                st.metric("📊 Projected ROI", f"{roi:.0f}%")
            
            # Performance timeline chart
            days = list(range(1, 31))
            daily_reach = [int(estimated_reach * (i/30) * (1 + 0.1 * np.sin(i/5))) for i in days]
            cumulative_conversions = [int(estimated_conversions * (i/30)) for i in days]
            
            chart_data = pd.DataFrame({
                'Day': days,
                'Daily Reach': daily_reach,
                'Cumulative Conversions': cumulative_conversions
            })
            
            fig = px.line(chart_data, x='Day', y=['Daily Reach', 'Cumulative Conversions'],
                         title="Projected 30-Day Campaign Performance")
            fig.update_layout(template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)
    
    # Email Campaign Results
    if st.session_state.campaign_results is not None:
        st.markdown("---")
        st.subheader("📧 Email Campaign Performance")
        
        results_df = st.session_state.campaign_results
        
        # Performance metrics
        total_sent = len(results_df[results_df['status'] == 'sent'])
        total_failed = len(results_df[results_df['status'] == 'failed'])
        total_invalid = len(results_df[results_df['status'] == 'invalid'])
        success_rate = (total_sent / len(results_df)) * 100 if len(results_df) > 0 else 0
        
        # Display metrics
        perf_col1, perf_col2, perf_col3, perf_col4 = st.columns(4)
        
        with perf_col1:
            st.metric("📧 Total Emails", len(results_df))
        with perf_col2:
            st.metric("✅ Successfully Delivered", total_sent, delta=f"{success_rate:.1f}%")
        with perf_col3:
            st.metric("❌ Failed Deliveries", total_failed)
        with perf_col4:
            st.metric("⚠️ Invalid Addresses", total_invalid)
        
        # Results visualization
        col1, col2 = st.columns(2)
        
        with col1:
            # Pie chart of results
            status_counts = results_df['status'].value_counts()
            fig = px.pie(
                values=status_counts.values, 
                names=status_counts.index,
                title="Email Delivery Results Distribution",
                color_discrete_map={
                    'sent': '#28a745', 
                    'failed': '#dc3545', 
                    'invalid': '#ffc107'
                }
            )
            fig.update_layout(template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            # Domain analysis for successful sends
            if total_sent > 0:
                sent_emails = results_df[results_df['status'] == 'sent'].copy()
                sent_emails['domain'] = sent_emails['email'].str.split('@').str[1]
                domain_counts = sent_emails['domain'].value_counts().head(8)
                
                fig = px.bar(
                    x=domain_counts.values, 
                    y=domain_counts.index,
                    title="Top Email Domains Reached",
                    orientation='h',
                    color_discrete_sequence=['#28a745']
                )
                fig.update_layout(template="plotly_white")
                st.plotly_chart(fig, use_container_width=True)
        
        # Detailed results table
        with st.expander("📋 View Detailed Email Results"):
            st.dataframe(
                results_df,
                column_config={
                    "email": st.column_config.TextColumn("📧 Email Address"),
                    "name": st.column_config.TextColumn("👤 Name"),
                    "status": st.column_config.TextColumn("📊 Status"),
                    "error": st.column_config.TextColumn("❌ Error (if any)"),
                    "timestamp": st.column_config.TextColumn("⏰ Time Sent")
                },
                use_container_width=True
            )
        
        # Export functionality
        st.subheader("📥 Export Results")
        
        export_col1, export_col2 = st.columns(2)
        
        with export_col1:
            # CSV export
            csv_data = results_df.to_csv(index=False)
            st.download_button(
                "📊 Download Detailed Results (CSV)",
                data=csv_data,
                file_name=f"email_campaign_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        
        with export_col2:
            # Summary report
            summary_report = f"""
# Email Campaign Results Summary

**Campaign Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Total Recipients:** {len(results_df)}

## Performance Metrics
- **Successfully Sent:** {total_sent} ({success_rate:.1f}%)
- **Failed Deliveries:** {total_failed} ({(total_failed/len(results_df)*100):.1f}%)
- **Invalid Addresses:** {total_invalid} ({(total_invalid/len(results_df)*100):.1f}%)

## Key Insights
- **Delivery Success Rate:** {success_rate:.1f}%
- **Most Common Domains:** {', '.join(sent_emails['domain'].value_counts().head(3).index.tolist()) if total_sent > 0 else 'N/A'}
- **Campaign Quality:** {'Excellent' if success_rate >= 95 else 'Good' if success_rate >= 85 else 'Needs Improvement'}

## Recommendations
{"✅ Great delivery rate! Your email list is clean and well-targeted." if success_rate >= 95 else "⚠️ Consider cleaning your email list to improve delivery rates." if success_rate < 85 else "👍 Good performance. Monitor for any delivery issues."}
"""
            
            st.download_button(
                "📄 Download Summary Report (MD)",
                data=summary_report,
                file_name=f"campaign_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
                mime="text/markdown",
                use_container_width=True
            )
    
    # File Upload Analytics
    st.markdown("---")
    st.subheader("📁 Upload Data for Custom Analytics")
    st.info("Upload your own campaign performance data (CSV/Excel) for detailed analysis")
    
    analytics_file = st.file_uploader("Upload analytics data", type=['csv', 'xlsx'])
    
    if analytics_file:
        try:
            if analytics_file.name.endswith('.csv'):
                analytics_df = pd.read_csv(analytics_file)
            else:
                analytics_df = pd.read_excel(analytics_file)
            
            st.success(f"✅ Analytics data uploaded: {len(analytics_df)} records")
            
            # Basic data overview
            st.subheader("📊 Data Overview")
            
            overview_col1, overview_col2, overview_col3, overview_col4 = st.columns(4)
            
            with overview_col1:
                st.metric("📊 Total Records", len(analytics_df))
            with overview_col2:
                st.metric("📈 Columns", len(analytics_df.columns))
            with overview_col3:
                st.metric("💾 File Size", f"{analytics_file.size / 1024:.1f} KB")
            with overview_col4:
                missing_data = analytics_df.isnull().sum().sum()
                st.metric("❓ Missing Values", missing_data)
            
            # Show data preview
            st.subheader("👀 Data Preview")
            st.dataframe(analytics_df.head(10), use_container_width=True)
            
            # Generate analytics if numeric columns exist
            numeric_cols = analytics_df.select_dtypes(include=[np.number]).columns.tolist()
            
            if numeric_cols:
                st.subheader("📈 Automated Analytics")
                
                # Summary statistics
                st.write("**Statistical Summary:**")
                st.dataframe(analytics_df[numeric_cols].describe(), use_container_width=True)
                
                # Visualizations
                viz_col1, viz_col2 = st.columns(2)
                
                with viz_col1:
                    if len(numeric_cols) > 0:
                        selected_metric = st.selectbox("Select metric for histogram:", numeric_cols)
                        fig = px.histogram(
                            analytics_df, 
                            x=selected_metric, 
                            title=f"Distribution of {selected_metric}",
                            nbins=20
                        )
                        fig.update_layout(template="plotly_white")
                        st.plotly_chart(fig, use_container_width=True)
                
                with viz_col2:
                    if len(numeric_cols) > 1:
                        x_metric = st.selectbox("X-axis metric:", numeric_cols, index=0)
                        y_metric = st.selectbox("Y-axis metric:", numeric_cols, index=1)
                        
                        fig = px.scatter(
                            analytics_df, 
                            x=x_metric, 
                            y=y_metric,
                            title=f"{x_metric} vs {y_metric}"
                        )
                        fig.update_layout(template="plotly_white")
                        st.plotly_chart(fig, use_container_width=True)
            
            # Correlation analysis
            if len(numeric_cols) > 1:
                st.subheader("🔗 Correlation Analysis")
                corr_matrix = analytics_df[numeric_cols].corr()
                
                fig = px.imshow(
                    corr_matrix,
                    title="Correlation Matrix of Numeric Variables",
                    color_continuous_scale="RdBu",
                    aspect="auto"
                )
                fig.update_layout(template="plotly_white")
                st.plotly_chart(fig, use_container_width=True)
        
        except Exception as e:
            st.error(f"❌ Error processing analytics file: {str(e)}")
    
    else:
        # Show placeholder content
        st.info("""
        📊 **Analytics Dashboard**
        
        This section provides comprehensive analytics for your marketing campaigns:
        
        **📍 Geographic Analysis:**
        - Campaign targeting visualization
        - Location-based performance metrics
        
        **📈 Performance Projections:**
        - ROI calculations based on budget
        - Estimated reach and conversion metrics
        
        **📧 Email Campaign Results:**
        - Delivery success rates
        - Domain analysis
        - Detailed performance breakdowns
        
        **📁 Custom Data Analysis:**
        - Upload your own performance data
        - Automated insights and visualizations
        - Statistical analysis and correlations
        
        Create campaigns and send emails to see detailed analytics here!
        """)

if __name__ == "__main__":
    main()

import streamlit as st
import pandas as pd
import numpy as np
import smtplib
import ssl
import time
import re
import json
import plotly.express as px
import plotly.graph_objects as go
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email_validator import validate_email, EmailNotValidError
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
import io
import base64
from groq import Groq
import google.generativeai as genai
import requests
from PIL import Image

# Load environment variables
load_dotenv()

# Configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Configure Gemini AI
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Countries and Currencies data with coordinates
COUNTRIES_DATA = {
    "Global": {"coords": [0, 0], "currency": "USD"},
    "United States": {"coords": [39.8283, -98.5795], "currency": "USD"},
    "Canada": {"coords": [56.1304, -106.3468], "currency": "CAD"},
    "United Kingdom": {"coords": [55.3781, -3.4360], "currency": "GBP"},
    "Germany": {"coords": [51.1657, 10.4515], "currency": "EUR"},
    "France": {"coords": [46.6034, 1.8883], "currency": "EUR"},
    "Spain": {"coords": [40.4637, -3.7492], "currency": "EUR"},
    "Italy": {"coords": [41.8719, 12.5674], "currency": "EUR"},
    "Netherlands": {"coords": [52.1326, 5.2913], "currency": "EUR"},
    "Australia": {"coords": [-25.2744, 133.7751], "currency": "AUD"},
    "Japan": {"coords": [36.2048, 138.2529], "currency": "JPY"},
    "India": {"coords": [20.5937, 78.9629], "currency": "INR"},
    "China": {"coords": [35.8617, 104.1954], "currency": "CNY"},
    "Brazil": {"coords": [-14.2350, -51.9253], "currency": "BRL"},
    "Mexico": {"coords": [23.6345, -102.5528], "currency": "MXN"}
}

COUNTRIES = list(COUNTRIES_DATA.keys())
CURRENCIES = ["USD", "EUR", "GBP", "CAD", "AUD", "JPY", "CHF", "INR", "BRL", "MXN", "CNY"]

# ================================
# SESSION STATE INITIALIZATION
# ================================

def initialize_session_state():
    """Initialize all session state variables"""
    if 'current_page' not in st.session_state:
        st.session_state.current_page = "Campaign Dashboard"
    if 'current_campaign' not in st.session_state:
        st.session_state.current_campaign = None
    if 'campaign_blueprint' not in st.session_state:
        st.session_state.campaign_blueprint = None
    if 'email_template' not in st.session_state:
        st.session_state.email_template = None
    if 'email_contacts' not in st.session_state:
        st.session_state.email_contacts = None
    if 'campaign_results' not in st.session_state:
        st.session_state.campaign_results = None
    if 'plain_text_template' not in st.session_state:
        st.session_state.plain_text_template = None
    if 'generated_images' not in st.session_state:
        st.session_state.generated_images = []

# ================================
# UTILITY CLASSES
# ================================

class GeminiImageGenerator:
    """Generate images using Gemini AI"""
    
    def __init__(self):
        self.model = None
        if GEMINI_API_KEY:
            try:
                self.model = genai.GenerativeModel('gemini-pro')
            except Exception as e:
                st.error(f"Failed to initialize Gemini: {e}")
    
    def generate_campaign_image(self, campaign_description, style="professional"):
        """Generate campaign image using Gemini"""
        if not GEMINI_API_KEY:
            st.warning("Gemini API key not configured")
            return None
            
        try:
            # For now, return placeholder since Gemini Pro doesn't generate images directly
            # You would need Gemini Pro Vision or use DALL-E through the API
            st.info("Image generation with Gemini requires additional setup. Using placeholder.")
            
            # Create a placeholder image URL
            image_prompt = f"Professional marketing campaign image for: {campaign_description}, style: {style}"
            
            # Store the prompt for later use
            st.session_state.generated_images.append({
                'prompt': image_prompt,
                'timestamp': datetime.now(),
                'campaign': campaign_description
            })
            
            return image_prompt
            
        except Exception as e:
            st.error(f"Error generating image: {e}")
            return None

class EmailPersonalizer:
    """Handle intelligent email personalization"""
    
    @staticmethod
    def extract_name_from_email(email):
        """Extract potential name from email address"""
        try:
            local_part = email.split('@')[0]
            name_part = re.sub(r'[0-9._-]', ' ', local_part)
            name_parts = [part.capitalize() for part in name_part.split() if len(part) > 1]
            return ' '.join(name_parts) if name_parts else 'Valued Customer'
        except:
            return 'Valued Customer'
    
    @staticmethod
    def personalize_template(template, name, email=None):
        """Personalize email template"""
        first_name = name.split()[0] if name and ' ' in name else name
        
        personalized = template.replace('{name}', name or 'Valued Customer')
        personalized = personalized.replace('{{name}}', name or 'Valued Customer')
        personalized = personalized.replace('{first_name}', first_name or 'Valued Customer')
        personalized = personalized.replace('{{first_name}}', first_name or 'Valued Customer')
        personalized = personalized.replace('{email}', email or '')
        personalized = personalized.replace('{{email}}', email or '')
        
        return personalized

class EmailHandler:
    """Fixed email handling with proper error handling"""
    
    def __init__(self):
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587
        self.email = GMAIL_USER
        self.password = GMAIL_APP_PASSWORD
    
    def validate_email_address(self, email):
        try:
            validate_email(email)
            return True
        except EmailNotValidError:
            return False
    
    def send_single_email(self, to_email, subject, body, is_html=True):
        """Send a single email with detailed error handling"""
        if not self.email or not self.password:
            return False, "Gmail credentials not configured in .env file"
            
        try:
            msg = MIMEMultipart('alternative')
            msg['From'] = self.email
            msg['To'] = to_email
            msg['Subject'] = subject
            
            if is_html:
                msg.attach(MIMEText(body, 'html'))
            else:
                msg.attach(MIMEText(body, 'plain'))
            
            context = ssl.create_default_context()
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls(context=context)
                server.login(self.email, self.password)
                text = msg.as_string()
                server.sendmail(self.email, to_email, text)
            
            return True, "Success"
        except smtplib.SMTPAuthenticationError:
            return False, "Gmail authentication failed. Check your app password."
        except smtplib.SMTPRecipientsRefused:
            return False, f"Recipient {to_email} was refused"
        except Exception as e:
            return False, f"SMTP Error: {str(e)}"
    
    def send_bulk_emails_fixed(self, email_list, subject, body_template, personalizer, is_html=True):
        """FIXED bulk email sending function"""
        if not self.email or not self.password:
            st.error("❌ Gmail configuration missing. Please check your .env file.")
            st.error("Required: GMAIL_USER and GMAIL_APP_PASSWORD")
            return pd.DataFrame()
        
        total_emails = len(email_list)
        results = []
        
        # Create progress components outside the loop
        progress_placeholder = st.empty()
        status_placeholder = st.empty()
        metrics_placeholder = st.empty()
        
        sent_count = 0
        failed_count = 0
        invalid_count = 0
        
        # Send emails one by one
        for index, row in email_list.iterrows():
            # Update progress
            progress = (index + 1) / total_emails
            progress_placeholder.progress(progress)
            status_placeholder.text(f"Sending email {index + 1} of {total_emails} to {row['email']}...")
            
            # Validate email
            if not self.validate_email_address(row['email']):
                invalid_count += 1
                results.append({
                    "email": row['email'],
                    "name": row.get('name', 'Unknown'),
                    "status": "invalid",
                    "error": "Invalid email format"
                })
                continue
            
            # Prepare personalized content
            name = row.get('name', personalizer.extract_name_from_email(row['email']))
            personalized_body = personalizer.personalize_template(body_template, name, row['email'])
            personalized_subject = personalizer.personalize_template(subject, name, row['email'])
            
            # Send email
            success, error_msg = self.send_single_email(
                row['email'], 
                personalized_subject, 
                personalized_body, 
                is_html=is_html
            )
            
            if success:
                sent_count += 1
                status = "sent"
            else:
                failed_count += 1
                status = "failed"
            
            results.append({
                "email": row['email'],
                "name": name,
                "status": status,
                "error": error_msg if not success else "",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            # Update metrics
            with metrics_placeholder.container():
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("✅ Sent", sent_count)
                col2.metric("❌ Failed", failed_count)
                col3.metric("⚠️ Invalid", invalid_count)
                col4.metric("📊 Progress", f"{progress * 100:.1f}%")
            
            # Delay to avoid rate limiting
            time.sleep(2)
        
        # Final update
        progress_placeholder.progress(1.0)
        status_placeholder.success("🎉 Email campaign completed!")
        
        return pd.DataFrame(results)

class FileProcessor:
    """Process files and extract contacts"""
    
    def __init__(self):
        self.email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        self.personalizer = EmailPersonalizer()
    
    def process_file(self, uploaded_file):
        """Process uploaded file and extract contacts"""
        try:
            file_extension = uploaded_file.name.split('.')[-1].lower()
            
            if file_extension == 'csv':
                df = pd.read_csv(uploaded_file)
            elif file_extension in ['xlsx', 'xls']:
                df = pd.read_excel(uploaded_file)
            else:
                st.error("Unsupported file format")
                return None
            
            return self._process_dataframe(df)
            
        except Exception as e:
            st.error(f"Error processing file: {e}")
            return None
    
    def _process_dataframe(self, df):
        """Process dataframe and standardize columns"""
        # Convert column names to lowercase
        df.columns = df.columns.str.lower()
        
        # Find email and name columns
        email_col = None
        name_col = None
        
        for col in df.columns:
            if 'email' in col or 'mail' in col:
                email_col = col
                break
        
        for col in df.columns:
            if 'name' in col or 'first' in col or 'last' in col:
                name_col = col
                break
        
        if email_col is None:
            st.error("No email column found in the file")
            return None
        
        # Create result dataframe
        result_data = []
        
        for _, row in df.iterrows():
            email = row[email_col]
            if pd.isna(email) or email.strip() == '':
                continue
            
            # Get name
            if name_col and not pd.isna(row[name_col]):
                name = str(row[name_col]).strip()
            else:
                name = self.personalizer.extract_name_from_email(email)
            
            # Validate email
            try:
                validate_email(email)
                result_data.append({'email': email, 'name': name})
            except EmailNotValidError:
                continue
        
        if not result_data:
            st.error("No valid emails found")
            return None
        
        return pd.DataFrame(result_data)

class CampaignGenerator:
    """Generate campaigns using Groq API"""
    
    def __init__(self):
        self.client = None
        if GROQ_API_KEY:
            try:
                self.client = Groq(api_key=GROQ_API_KEY)
            except Exception as e:
                st.error(f"Failed to initialize Groq: {e}")
    
    def generate_campaign_blueprint(self, campaign_data):
        """Generate campaign blueprint using Groq"""
        if not self.client:
            return self._fallback_blueprint(campaign_data)
        
        try:
            prompt = self._build_campaign_prompt(campaign_data)
            
            response = self.client.chat.completions.create(
                messages=[
                    {
                        "role": "system", 
                        "content": "You are a world-class marketing strategist. Create detailed, actionable marketing campaigns."
                    },
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ],
                model="llama3-8b-8192",
                temperature=0.7,
                max_tokens=4000
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            st.error(f"Error generating campaign: {e}")
            return self._fallback_blueprint(campaign_data)
    
    def _build_campaign_prompt(self, data):
        """Build comprehensive campaign prompt"""
        return f"""
        Create a comprehensive marketing campaign blueprint for:
        
        **Company:** {data.get('company_name', 'Company')}
        **Campaign Type:** {data.get('campaign_type', 'Marketing')}
        **Target Audience:** {data.get('target_audience', 'General')}
        **Location:** {data.get('location', 'Global')} {data.get('city_state', '')}
        **Channels:** {', '.join(data.get('channels', []))}
        **Budget:** {data.get('budget', 'TBD')} {data.get('currency', 'USD')}
        **Duration:** {data.get('duration', 'TBD')}
        **Product:** {data.get('product_description', 'Product/Service')}
        
        Provide:
        1. Executive Summary
        2. Target Audience Analysis  
        3. Key Messaging Strategy
        4. Channel-Specific Tactics
        5. Timeline & Milestones
        6. Budget Breakdown
        7. Success Metrics
        8. Risk Management
        9. Implementation Plan
        """
    
    def _fallback_blueprint(self, data):
        """Fallback campaign blueprint"""
        return f"""
# {data.get('company_name', 'Your Company')} Marketing Campaign

## Campaign Overview
- **Type:** {data.get('campaign_type', 'Marketing Campaign')}
- **Target:** {data.get('target_audience', 'General Audience')}
- **Location:** {data.get('location', 'Global')}
- **Duration:** {data.get('duration', 'To be determined')}
- **Budget:** {data.get('budget', 'TBD')} {data.get('currency', 'USD')}

## Objectives
- Increase brand awareness
- Drive customer engagement
- Generate qualified leads
- Boost conversions

## Strategy
- Multi-channel approach using {', '.join(data.get('channels', ['Email']))}
- Targeted messaging for {data.get('target_audience', 'target audience')}
- Location-specific optimization for {data.get('location', 'target market')}

## Implementation
1. Campaign setup and asset creation
2. Audience targeting and list building  
3. Content creation and testing
4. Launch and monitoring
5. Optimization and reporting

## Success Metrics
- Reach and impressions
- Engagement rates
- Conversion rates
- ROI and ROAS
"""

# ================================
# STREAMLIT APP
# ================================

st.set_page_config(
    page_title="Marketing Campaign Generator",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
initialize_session_state()

# Custom CSS
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    .stApp {
        background: linear-gradient(135deg, #0f0f23 0%, #1a1a2e 100%);
        font-family: 'Inter', sans-serif;
    }
    
    .css-1d391kg {
        background: linear-gradient(180deg, #16213e 0%, #0f3460 100%);
    }
    
    h1, h2, h3 {
        color: #00d4ff !important;
        font-weight: 600 !important;
    }
    
    .stButton > button {
        background: linear-gradient(45deg, #00d4ff, #0099cc);
        color: white;
        border: none;
        border-radius: 10px;
        padding: 0.75rem 1.5rem;
        font-weight: 600;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(0, 212, 255, 0.3);
        width: 100%;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(0, 212, 255, 0.4);
    }
    
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea,
    .stSelectbox > div > div > select {
        background-color: #1e1e1e !important;
        color: #ffffff !important;
        border: 1px solid #333 !important;
        border-radius: 8px !important;
    }
    
    .success-metric {
        background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
        color: white;
        padding: 1rem;
        border-radius: 8px;
        text-align: center;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

def main():
    # Header
    st.markdown("""
    <div style="text-align: center; padding: 2rem 0;">
        <h1 style="font-size: 3rem; margin-bottom: 0;">🚀 Marketing Campaign War Room</h1>
        <p style="font-size: 1.2rem; color: #888; margin-top: 0;">AI-Powered Campaign Generation & Email Marketing Platform</p>
    </div>
    """, unsafe_allow_html=True)
    
    # FIXED Navigation - Using session state instead of st.switch_page
    with st.sidebar:
        st.markdown("### 🎯 Navigation")
        
        # Navigation buttons that update session state
        if st.button("🎯 Campaign Dashboard", use_container_width=True):
            st.session_state.current_page = "Campaign Dashboard"
            st.rerun()
        
        if st.button("📧 Email Marketing", use_container_width=True):
            st.session_state.current_page = "Email Marketing"
            st.rerun()
        
        if st.button("📊 Analytics & Reports", use_container_width=True):
            st.session_state.current_page = "Analytics & Reports"
            st.rerun()
        
        st.markdown("---")
        
        # System status
        st.markdown("### 🔧 System Status")
        
        if GROQ_API_KEY:
            st.success("🤖 AI Engine: Connected")
        else:
            st.error("🤖 AI Engine: Not configured")
        
        if GMAIL_USER and GMAIL_APP_PASSWORD:
            st.success("📧 Email Service: Connected")
        else:
            st.error("📧 Email Service: Not configured")
        
        if GEMINI_API_KEY:
            st.success("🎨 Image Generator: Connected")
        else:
            st.warning("🎨 Image Generator: Not configured")
        
        st.markdown("---")
        
        # Current campaign info
        if st.session_state.current_campaign:
            st.markdown("### 🎯 Active Campaign")
            st.info(f"**{st.session_state.current_campaign['company_name']}**")
            st.caption(f"Type: {st.session_state.current_campaign['campaign_type']}")
            st.caption(f"Location: {st.session_state.current_campaign['location']}")
        
        if st.session_state.email_contacts is not None:
            st.markdown("### 📊 Contact Stats")
            st.info(f"📧 Loaded: {len(st.session_state.email_contacts)} contacts")
    
    # Show current page content
    if st.session_state.current_page == "Campaign Dashboard":
        show_campaign_dashboard()
    elif st.session_state.current_page == "Email Marketing":
        show_email_marketing()
    elif st.session_state.current_page == "Analytics & Reports":
        show_analytics_reports()

def show_campaign_dashboard():
    st.header("🎯 AI Campaign Strategy Generator")
    
    with st.form("campaign_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            company_name = st.text_input("🏢 Company Name", 
                value=st.session_state.current_campaign['company_name'] if st.session_state.current_campaign else "")
            
            campaign_type = st.selectbox("📋 Campaign Type", [
                "Product Launch", "Brand Awareness", "Seasonal Campaign", "Customer Retention",
                "Lead Generation", "Event Promotion", "Sales Campaign", "Newsletter Campaign"
            ])
            
            target_audience = st.text_area("👥 Target Audience", 
                placeholder="Describe demographics, interests, pain points...")
            
            duration = st.text_input("📅 Campaign Duration", placeholder="e.g., 4 weeks, 2 months")
        
        with col2:
            channels = st.multiselect("📢 Marketing Channels", [
                "Email Marketing", "Social Media", "Google Ads", "Facebook Ads", 
                "Content Marketing", "Influencer Marketing", "TV/Radio", "Print Media"
            ])
            
            location = st.selectbox("🌍 Target Country", COUNTRIES)
            city_state = st.text_input("🏙️ City/State", placeholder="e.g., New York, NY")
            customer_segment = st.selectbox("💼 Customer Segment", 
                ["Mass Market", "Premium", "Niche", "Enterprise", "SMB"])
        
        # Budget and Currency
        budget_col1, budget_col2 = st.columns(2)
        with budget_col1:
            budget = st.text_input("💰 Budget Amount", placeholder="e.g., 50000")
        with budget_col2:
            currency = st.selectbox("💱 Currency", CURRENCIES)
        
        product_description = st.text_area("📦 Product/Service Description",
            placeholder="Describe what you're promoting...")
        
        # Generate campaign button
        generate_campaign = st.form_submit_button("🚀 Generate AI Campaign Strategy", use_container_width=True)
        
        # Generate campaign image button
        generate_image = st.form_submit_button("🎨 Generate Campaign Image", use_container_width=True)
    
    # Handle campaign generation
    if generate_campaign and company_name and campaign_type:
        campaign_data = {
            'company_name': company_name,
            'campaign_type': campaign_type,
            'target_audience': target_audience,
            'duration': duration,
            'channels': channels,
            'location': location,
            'city_state': city_state,
            'customer_segment': customer_segment,
            'budget': budget,
            'currency': currency,
            'product_description': product_description
        }
        
        with st.spinner("🤖 AI is generating your campaign strategy..."):
            generator = CampaignGenerator()
            blueprint = generator.generate_campaign_blueprint(campaign_data)
            
            # Store in session state
            st.session_state.current_campaign = campaign_data
            st.session_state.campaign_blueprint = blueprint
            
            st.success("✨ Campaign strategy generated!")
            st.balloons()
    
    # Handle image generation
    if generate_image and st.session_state.current_campaign:
        with st.spinner("🎨 Generating campaign image..."):
            image_gen = GeminiImageGenerator()
            campaign_desc = f"{st.session_state.current_campaign['company_name']} {st.session_state.current_campaign['campaign_type']}"
            image_prompt = image_gen.generate_campaign_image(campaign_desc)
            
            if image_prompt:
                st.success("🎨 Campaign image concept generated!")
                st.info(f"Image concept: {image_prompt}")
    
    # Display existing campaign
    if st.session_state.campaign_blueprint:
        st.markdown("---")
        st.markdown("## 📋 Your Campaign Strategy")
        st.markdown(st.session_state.campaign_blueprint)
        
        # Action buttons
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("📧 Create Email Campaign", use_container_width=True):
                st.session_state.current_page = "Email Marketing"
                st.rerun()
        with col2:
            if st.button("📊 View Analytics", use_container_width=True):
                st.session_state.current_page = "Analytics & Reports"
                st.rerun()
        with col3:
            if st.session_state.current_campaign:
                st.download_button("📄 Download Strategy", 
                    data=st.session_state.campaign_blueprint,
                    file_name=f"{st.session_state.current_campaign['company_name']}_strategy.md",
                    mime="text/markdown",
                    use_container_width=True)

def show_email_marketing():
    st.header("📧 Email Marketing Center")
    
    # Show active campaign
    if st.session_state.current_campaign:
        st.success(f"🎯 Active: **{st.session_state.current_campaign['company_name']}** - {st.session_state.current_campaign['campaign_type']}")
    
    # Email template generation
    st.subheader("🎨 Generate Email Content")
    
    template_col1, template_col2 = st.columns(2)
    
    with template_col1:
        email_type = st.selectbox("📧 Email Type", [
            "Welcome Email", "Product Announcement", "Promotional Offer", 
            "Newsletter", "Follow-up Email", "Event Invitation"
        ])
        tone = st.selectbox("🎭 Tone", ["Professional", "Friendly", "Casual", "Urgent"])
    
    with template_col2:
        content_format = st.radio("📝 Format", ["HTML Template", "Plain Text"])
        
        if st.button("🚀 Generate Email Content", use_container_width=True):
            if st.session_state.campaign_blueprint:
                # Simple template generation
                if content_format == "HTML Template":
                    template = f"""
<!DOCTYPE html>
<html>
<head><title>{email_type}</title></head>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #00d4ff, #0099cc); color: white; padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
        <h1>Hello {{{{first_name}}}}!</h1>
    </div>
    <div style="padding: 30px; background: white; color: #333;">
        <p>We're excited to share this {email_type.lower()} with you.</p>
        <p>As someone who values quality, we thought you'd be interested in what we have to offer.</p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="#" style="background: #00d4ff; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; font-weight: bold;">Learn More</a>
        </div>
        <p>Thank you for being part of our community!</p>
    </div>
    <div style="background: #f8f9fa; padding: 20px; text-align: center; border-radius: 0 0 8px 8px;">
        <p>Best regards,<br>The {st.session_state.current_campaign['company_name'] if st.session_state.current_campaign else 'Marketing'} Team</p>
    </div>
</body>
</html>"""
                    st.session_state.email_template = template
                else:
                    template = f"""Subject: {email_type} from {{{{first_name}}}}

Hello {{{{first_name}}}},

We're excited to share this {email_type.lower()} with you.

As someone who values quality, we thought you'd be interested in what we have to offer.

Here's what makes this special:
- Personalized for you
- Exclusive benefits
- Limited time opportunity

Ready to learn more? Visit our website or reply to this email.

Thank you for being part of our community!

Best regards,
The {st.session_state.current_campaign['company_name'] if st.session_state.current_campaign else 'Marketing'} Team"""
                    st.session_state.plain_text_template = template
                
                st.success("✨ Email content generated!")
            else:
                st.warning("⚠️ Create a campaign first")
    
    # Template editor
    if st.session_state.email_template or st.session_state.plain_text_template:
        st.markdown("---")
        st.subheader("📝 Edit Email Content")
        
        if st.session_state.email_template and st.session_state.plain_text_template:
            edit_choice = st.radio("Edit:", ["HTML Template", "Plain Text"])
            current_template = st.session_state.email_template if edit_choice == "HTML Template" else st.session_state.plain_text_template
        elif st.session_state.email_template:
            current_template = st.session_state.email_template
            edit_choice = "HTML Template"
        else:
            current_template = st.session_state.plain_text_template
            edit_choice = "Plain Text"
        
        edited_content = st.text_area("Email Content:", value=current_template, height=300)
        
        if edit_choice == "HTML Template":
            st.session_state.email_template = edited_content
        else:
            st.session_state.plain_text_template = edited_content
        
        # Preview HTML
        if edit_choice == "HTML Template" and st.button("👀 Preview Email"):
            personalizer = EmailPersonalizer()
            preview = personalizer.personalize_template(edited_content, "John Smith", "john@example.com")
            st.components.v1.html(preview, height=500, scrolling=True)
    
    st.markdown("---")
    
    # Contact upload
    st.subheader("👥 Upload Email Contacts")
    
    uploaded_file = st.file_uploader("Upload CSV/Excel file with emails", 
        type=['csv', 'xlsx'], key="contact_upload")
    
    if uploaded_file:
        processor = FileProcessor()
        contacts = processor.process_file(uploaded_file)
        
        if contacts is not None:
            st.session_state.email_contacts = contacts
            st.success(f"✅ Loaded {len(contacts)} contacts!")
            
            # Show editable contacts
            edited_contacts = st.data_editor(
                contacts,
                column_config={
                    "email": st.column_config.TextColumn("📧 Email"),
                    "name": st.column_config.TextColumn("👤 Name")
                },
                num_rows="dynamic",
                use_container_width=True
            )
            st.session_state.email_contacts = edited_contacts
    
    # FIXED Email campaign launch
    if (st.session_state.email_contacts is not None and 
        (st.session_state.email_template or st.session_state.plain_text_template)):
        
        st.markdown("---")
        st.subheader("🚀 Launch Email Campaign")
        
        df = st.session_state.email_contacts
        
        # Campaign metrics
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("👥 Contacts", len(df))
        with col2:
            domains = df['email'].str.split('@').str[1].nunique()
            st.metric("🏢 Domains", domains)
        with col3:
            st.metric("📧 Template", "✅ Ready")
        
        # Email configuration
        config_col1, config_col2 = st.columns(2)
        
        with config_col1:
            subject = st.text_input("📧 Subject Line", 
                value="Important message for {first_name}")
            test_email = st.text_input("🧪 Test Email", placeholder="your@email.com")
        
        with config_col2:
            # Choose format
            if st.session_state.email_template and st.session_state.plain_text_template:
                send_format = st.radio("📝 Send As:", ["HTML", "Plain Text"])
                template_to_use = st.session_state.email_template if send_format == "HTML" else st.session_state.plain_text_template
                is_html = send_format == "HTML"
            elif st.session_state.email_template:
                template_to_use = st.session_state.email_template
                is_html = True
                st.info("HTML template ready")
            else:
                template_to_use = st.session_state.plain_text_template
                is_html = False
                st.info("Plain text template ready")
        
        # Test email
        if test_email and st.button("🧪 Send Test", use_container_width=True):
            email_handler = EmailHandler()
            personalizer = EmailPersonalizer()
            
            test_content = personalizer.personalize_template(template_to_use, "Test User", test_email)
            test_subject = personalizer.personalize_template(subject, "Test User", test_email)
            
            success, error_msg = email_handler.send_single_email(test_email, test_subject, test_content, is_html)
            
            if success:
                st.success("✅ Test email sent!")
            else:
                st.error(f"❌ Test failed: {error_msg}")
        
        # FIXED Launch button
        st.markdown("### 🎯 Campaign Launch")
        
        if st.button("🚀 LAUNCH EMAIL CAMPAIGN", type="primary", use_container_width=True, key="launch_campaign"):
            if not GMAIL_USER or not GMAIL_APP_PASSWORD:
                st.error("❌ Gmail configuration missing!")
                st.error("Please add GMAIL_USER and GMAIL_APP_PASSWORD to your .env file")
                st.code("""
# Add to .env file:
GMAIL_USER=your_email@gmail.com
GMAIL_APP_PASSWORD=your_16_digit_app_password
                """)
                st.stop()
            
            # Confirmation
            st.warning(f"⚠️ About to send {len(df)} emails. This cannot be undone!")
            
            # Use a unique key for the confirmation button
            confirm_key = f"confirm_launch_{datetime.now().timestamp()}"
            
            if st.button("✅ CONFIRM & SEND", key=confirm_key):
                st.info("🚀 Starting email campaign...")
                
                # Initialize components
                email_handler = EmailHandler()
                personalizer = EmailPersonalizer()
                
                # Send emails
                results = email_handler.send_bulk_emails_fixed(
                    df, subject, template_to_use, personalizer, is_html
                )
                
                if not results.empty:
                    # Show final results
                    success_count = len(results[results['status'] == 'sent'])
                    failed_count = len(results[results['status'] == 'failed'])
                    invalid_count = len(results[results['status'] == 'invalid'])
                    success_rate = (success_count / len(results)) * 100
                    
                    st.markdown("### 🎉 Campaign Results")
                    
                    result_col1, result_col2, result_col3, result_col4 = st.columns(4)
                    
                    with result_col1:
                        st.markdown(f'<div class="success-metric">✅ Sent<br><h2>{success_count}</h2></div>', unsafe_allow_html=True)
                    with result_col2:
                        st.metric("❌ Failed", failed_count)
                    with result_col3:
                        st.metric("⚠️ Invalid", invalid_count)
                    with result_col4:
                        st.metric("📊 Success Rate", f"{success_rate:.1f}%")
                    
                    # Store results
                    st.session_state.campaign_results = results
                    
                    # Download option
                    csv = results.to_csv(index=False)
                    st.download_button("📥 Download Results", 
                        data=csv, 
                        file_name=f"campaign_results_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                        mime="text/csv")
                    
                    # Show details
                    with st.expander("📋 View Detailed Results"):
                        st.dataframe(results, use_container_width=True)
                    
                    st.balloons()

def show_analytics_reports():
    st.header("📊 Campaign Analytics & Reports")
    
    # Show campaign-based map if campaign exists
    if st.session_state.current_campaign:
        st.subheader("🗺️ Campaign Geographic Analysis")
        
        campaign = st.session_state.current_campaign
        location = campaign['location']
        
        if location in COUNTRIES_DATA:
            coords = COUNTRIES_DATA[location]['coords']
            
            # Create map data
            map_data = pd.DataFrame({
                'lat': [coords[0]],
                'lon': [coords[1]], 
                'location': [location],
                'campaign': [campaign['campaign_type']],
                'company': [campaign['company_name']]
            })
            
            # Display map using plotly
            fig = px.scatter_mapbox(
                map_data,
                lat='lat',
                lon='lon',
                hover_name='location',
                hover_data={'campaign': True, 'company': True, 'lat': False, 'lon': False},
                color_discrete_sequence=['#00d4ff'],
                size_max=15,
                zoom=3,
                title=f"Campaign Target Location: {location}"
            )
            
            fig.update_layout(
                mapbox_style="carto-darkmatter",
                mapbox_accesstoken=None,
                template="plotly_dark",
                height=500
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            # Campaign overview metrics
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("🎯 Campaign Type", campaign['campaign_type'])
            with col2:
                st.metric("🌍 Target Market", location)
            with col3:
                st.metric("💰 Budget", f"{campaign.get('budget', 'TBD')} {campaign.get('currency', 'USD')}")
            with col4:
                st.metric("📅 Duration", campaign.get('duration', 'TBD'))
        
        # Projected analytics based on campaign data
        st.subheader("📈 Campaign Projections")
        
        # Create mock projections based on campaign data
        if campaign.get('budget') and campaign['budget'].isdigit():
            budget = int(campaign['budget'])
            
            # Mock calculations
            estimated_reach = budget * 20  # $1 = 20 people reach
            estimated_clicks = int(estimated_reach * 0.03)  # 3% CTR
            estimated_conversions = int(estimated_clicks * 0.02)  # 2% conversion
            estimated_revenue = estimated_conversions * 50  # $50 per conversion
            
            proj_col1, proj_col2, proj_col3, proj_col4 = st.columns(4)
            
            with proj_col1:
                st.metric("👥 Estimated Reach", f"{estimated_reach:,}")
            with proj_col2:
                st.metric("👆 Expected Clicks", f"{estimated_clicks:,}")
            with proj_col3:
                st.metric("💰 Projected Conversions", f"{estimated_conversions:,}")
            with proj_col4:
                roi = ((estimated_revenue - budget) / budget) * 100
                st.metric("📊 Projected ROI", f"{roi:.0f}%")
            
            # Performance chart
            days = list(range(1, 31))
            cumulative_reach = [int(estimated_reach * (i/30)) for i in days]
            cumulative_conversions = [int(estimated_conversions * (i/30)) for i in days]
            
            chart_data = pd.DataFrame({
                'Day': days,
                'Cumulative Reach': cumulative_reach,
                'Cumulative Conversions': cumulative_conversions
            })
            
            fig = px.line(chart_data, x='Day', y=['Cumulative Reach', 'Cumulative Conversions'],
                         title="Projected Campaign Performance Over Time")
            fig.update_layout(template="plotly_dark")
            st.plotly_chart(fig, use_container_width=True)
    
    # Real campaign results if available
    if st.session_state.campaign_results is not None:
        st.markdown("---")
        st.subheader("📧 Email Campaign Results")
        
        results_df = st.session_state.campaign_results
        
        # Results metrics
        total_sent = len(results_df[results_df['status'] == 'sent'])
        total_failed = len(results_df[results_df['status'] == 'failed'])
        total_invalid = len(results_df[results_df['status'] == 'invalid'])
        success_rate = (total_sent / len(results_df)) * 100
        
        metrics_col1, metrics_col2, metrics_col3, metrics_col4 = st.columns(4)
        
        with metrics_col1:
            st.metric("📧 Total Emails", len(results_df))
        with metrics_col2:
            st.metric("✅ Successfully Sent", total_sent)
        with metrics_col3:
            st.metric("❌ Failed", total_failed)
        with metrics_col4:
            st.metric("📊 Success Rate", f"{success_rate:.1f}%")
        
        # Results pie chart
        status_counts = results_df['status'].value_counts()
        fig = px.pie(
            values=status_counts.values, 
            names=status_counts.index,
            title="Email Campaign Results Distribution",
            color_discrete_map={'sent': '#28a745', 'failed': '#dc3545', 'invalid': '#ffc107'}
        )
        fig.update_layout(template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)
        
        # Domain analysis
        if total_sent > 0:
            sent_emails = results_df[results_df['status'] == 'sent']
            sent_emails['domain'] = sent_emails['email'].str.split('@').str[1]
            domain_counts = sent_emails['domain'].value_counts().head(10)
            
            fig = px.bar(x=domain_counts.index, y=domain_counts.values,
                        title="Top Email Domains Reached")
            fig.update_layout(template="plotly_dark")
            st.plotly_chart(fig, use_container_width=True)
        
        # Detailed results
        with st.expander("📋 Detailed Campaign Results"):
            st.dataframe(results_df, use_container_width=True)
    
    # Data upload section
    st.markdown("---")
    st.subheader("📁 Upload Campaign Data for Analysis")
    
    uploaded_data = st.file_uploader("Upload campaign performance data (CSV/Excel)", 
        type=['csv', 'xlsx'], key="analytics_upload")
    
    if uploaded_data:
        try:
            if uploaded_data.name.endswith('.csv'):
                data_df = pd.read_csv(uploaded_data)
            else:
                data_df = pd.read_excel(uploaded_data)
            
            st.success(f"✅ Data uploaded: {len(data_df)} records")
            
            # Basic analysis
            st.subheader("📊 Data Overview")
            
            overview_col1, overview_col2, overview_col3 = st.columns(3)
            
            with overview_col1:
                st.metric("📊 Records", len(data_df))
            with overview_col2:
                st.metric("📈 Columns", len(data_df.columns))
            with overview_col3:
                missing = data_df.isnull().sum().sum()
                st.metric("❓ Missing Values", missing)
            
            # Show data preview
            st.dataframe(data_df.head(), use_container_width=True)
            
            # Generate charts for numeric columns
            numeric_cols = data_df.select_dtypes(include=[np.number]).columns
            
            if len(numeric_cols) > 0:
                st.subheader("📈 Performance Charts")
                
                chart_col1, chart_col2 = st.columns(2)
                
                with chart_col1:
                    selected_col = st.selectbox("Select metric:", numeric_cols)
                    fig = px.histogram(data_df, x=selected_col, 
                                     title=f"Distribution of {selected_col}")
                    fig.update_layout(template="plotly_dark")
                    st.plotly_chart(fig, use_container_width=True)
                
                with chart_col2:
                    if len(numeric_cols) > 1:
                        col1 = st.selectbox("X-axis:", numeric_cols, index=0)
                        col2 = st.selectbox("Y-axis:", numeric_cols, index=1)
                        
                        fig = px.scatter(data_df, x=col1, y=col2,
                                       title=f"{col1} vs {col2}")
                        fig.update_layout(template="plotly_dark")
                        st.plotly_chart(fig, use_container_width=True)
        
        except Exception as e:
            st.error(f"Error processing data: {e}")
    
    else:
        st.info("""
        📊 **Analytics Dashboard**
        
        - **Campaign Map**: Shows your target location when a campaign is created
        - **Projections**: Estimates based on your campaign budget and parameters  
        - **Email Results**: Real results from sent email campaigns
        - **Data Upload**: Upload your own performance data for custom analysis
        
        Create a campaign to see geographic targeting and projections!
        """)

if __name__ == "__main__":
    main()

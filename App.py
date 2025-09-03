import streamlit as st
import pandas as pd
import numpy as np
import smtplib
import ssl
import time
import re
import json
import plotly.express as px
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from email_validator import validate_email, EmailNotValidError
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
import io
from huggingface_hub import InferenceClient
from PIL import Image

# Load environment variables
load_dotenv()

# Configuration
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")  # App password
HF_TOKEN = os.getenv("HF_TOKEN")

# Countries data
COUNTRIES_DATA = {
    "Global": {"coords": [0, 0], "currency": "USD"},
    "United States": {"coords": [39.8283, -98.5795], "currency": "USD"},
    "Canada": {"coords": [56.1304, -106.3468], "currency": "CAD"},
    "United Kingdom": {"coords": [55.3781, -3.4360], "currency": "GBP"},
    "Germany": {"coords": [51.1657, 10.4515], "currency": "EUR"},
    "France": {"coords": [46.6034, 1.8883], "currency": "EUR"},
    "India": {"coords": [20.5937, 78.9629], "currency": "INR"},
    "Australia": {"coords": [-25.2744, 133.7751], "currency": "AUD"},
    "Japan": {"coords": [36.2048, 138.2529], "currency": "JPY"},
    "China": {"coords": [35.8617, 104.1954], "currency": "CNY"},
    "Brazil": {"coords": [-14.2350, -51.9253], "currency": "BRL"}
}

COUNTRIES = list(COUNTRIES_DATA.keys())
CURRENCIES = ["USD", "EUR", "GBP", "CAD", "AUD", "JPY", "INR", "BRL", "CNY"]

# ================================
# SESSION STATE INITIALIZATION
# ================================

def initialize_session_state():
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
                self.client = InferenceClient(
                    provider="together",
                    api_key=HF_TOKEN,
                )
            except Exception as e:
                st.error(f"Failed to initialize HuggingFace client: {e}")
    
    def generate_campaign_image(self, campaign_description, style="professional"):
        """Generate campaign image using HuggingFace FLUX"""
        if not HF_TOKEN:
            st.warning("⚠️ HuggingFace token not configured. Please add HF_TOKEN to your .env file")
            return None
            
        if not self.client:
            st.error("❌ HuggingFace client not initialized")
            return None
            
        try:
            prompt = f"Professional marketing campaign image for {campaign_description}, {style} style, high quality, vibrant colors, modern design, eye-catching, commercial photography"
            
            with st.spinner("🎨 Generating campaign image with HuggingFace FLUX..."):
                # Generate image using FLUX model
                image = self.client.text_to_image(
                    prompt,
                    model="black-forest-labs/FLUX.1-dev",
                )
                
                if image:
                    # Save to session state
                    image_data = {
                        'prompt': prompt,
                        'timestamp': datetime.now(),
                        'campaign': campaign_description,
                        'image': image
                    }
                    
                    st.session_state.generated_images.append(image_data)
                    
                    # Display the image
                    st.success("✨ Campaign image generated successfully!")
                    st.image(image, caption=f"Generated for: {campaign_description}", use_column_width=True)
                    
                    # Provide download option
                    img_bytes = io.BytesIO()
                    image.save(img_bytes, format='PNG')
                    img_bytes.seek(0)
                    
                    st.download_button(
                        "📥 Download Campaign Image",
                        data=img_bytes.getvalue(),
                        file_name=f"campaign_image_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
                        mime="image/png"
                    )
                    
                    return image
                else:
                    st.error("❌ Failed to generate image")
                    return None
            
        except Exception as e:
            st.error(f"❌ Error generating image: {str(e)}")
            st.info("💡 Make sure your HuggingFace token is valid")
            return None

# ================================
# SIMPLE EMAIL PERSONALIZER
# ================================

class EmailPersonalizer:
    @staticmethod
    def extract_name_from_email(email):
        try:
            local_part = email.split('@')[0]
            name_part = re.sub(r'[0-9._-]', ' ', local_part)
            name_parts = [part.capitalize() for part in name_part.split() if len(part) > 1]
            return ' '.join(name_parts) if name_parts else 'Valued Customer'
        except:
            return 'Valued Customer'
    
    @staticmethod
    def personalize_content(template, name, email=None):
        first_name = name.split()[0] if name and ' ' in name else name
        
        personalized = template.replace('{name}', name or 'Valued Customer')
        personalized = personalized.replace('{first_name}', first_name or 'Valued Customer')
        personalized = personalized.replace('{email}', email or '')
        
        return personalized

# ================================
# WORKING EMAIL HANDLER
# ================================

def send_bulk_emails_working(email_list, subject_template, body_template, progress_placeholder, status_placeholder):
    """WORKING bulk email function that actually sends emails"""
    
    if not GMAIL_USER or not GMAIL_PASSWORD:
        st.error("❌ Gmail credentials missing!")
        st.code("""
# Add to .env file:
GMAIL_USER=your_email@gmail.com
GMAIL_PASSWORD=your_16_digit_app_password
        """)
        return pd.DataFrame()
    
    results = []
    total_emails = len(email_list)
    personalizer = EmailPersonalizer()
    
    # Create SMTP connection
    context = ssl.create_default_context()
    
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            
            for idx, row in email_list.iterrows():
                # Update progress
                progress = (idx + 1) / total_emails
                progress_placeholder.progress(progress)
                status_placeholder.info(f"📧 Sending to: {row['email']} ({idx + 1}/{total_emails})")
                
                try:
                    # Validate email
                    validate_email(row['email'])
                    
                    # Create message
                    msg = MIMEMultipart('alternative')
                    
                    # Personalize content
                    name = row.get('name', personalizer.extract_name_from_email(row['email']))
                    personalized_subject = personalizer.personalize_content(subject_template, name, row['email'])
                    personalized_body = personalizer.personalize_content(body_template, name, row['email'])
                    
                    msg['Subject'] = personalized_subject
                    msg['From'] = formataddr(("Marketing Team", GMAIL_USER))
                    msg['To'] = row['email']
                    
                    # Attach content
                    if '<html>' in body_template.lower() or '<p>' in body_template.lower():
                        msg.attach(MIMEText(personalized_body, 'html'))
                    else:
                        msg.attach(MIMEText(personalized_body, 'plain'))
                    
                    # Send email
                    server.sendmail(GMAIL_USER, row['email'], msg.as_string())
                    
                    results.append({
                        'email': row['email'],
                        'name': name,
                        'status': 'sent',
                        'error': '',
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    })
                    
                    # Small delay to avoid rate limiting
                    time.sleep(1)
                    
                except EmailNotValidError:
                    results.append({
                        'email': row['email'],
                        'name': row.get('name', 'Unknown'),
                        'status': 'invalid',
                        'error': 'Invalid email format',
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    })
                    
                except Exception as e:
                    results.append({
                        'email': row['email'],
                        'name': row.get('name', 'Unknown'),
                        'status': 'failed',
                        'error': str(e),
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    })
            
            progress_placeholder.progress(1.0)
            status_placeholder.success("✅ Email campaign completed!")
            
    except Exception as e:
        st.error(f"❌ SMTP Connection Error: {str(e)}")
        return pd.DataFrame()
    
    return pd.DataFrame(results)

# ================================
# FILE PROCESSOR
# ================================

class FileProcessor:
    def __init__(self):
        self.personalizer = EmailPersonalizer()
    
    def process_file(self, uploaded_file):
        try:
            file_extension = uploaded_file.name.split('.')[-1].lower()
            
            if file_extension == 'csv':
                df = pd.read_csv(uploaded_file)
            elif file_extension in ['xlsx', 'xls']:
                df = pd.read_excel(uploaded_file)
            else:
                st.error("Please use CSV or Excel files only")
                return None
            
            # Convert column names to lowercase
            df.columns = df.columns.str.lower()
            
            # Find email column
            email_col = None
            for col in df.columns:
                if 'email' in col or 'mail' in col:
                    email_col = col
                    break
            
            if email_col is None:
                st.error("❌ No email column found. Please ensure your file has an 'email' column.")
                return None
            
            # Find name columns
            name_cols = []
            for col in df.columns:
                if any(keyword in col for keyword in ['name', 'first', 'last']):
                    name_cols.append(col)
            
            # Process contacts
            result_data = []
            for _, row in df.iterrows():
                email = row[email_col]
                if pd.isna(email) or str(email).strip() == '':
                    continue
                
                email = str(email).strip().lower()
                
                # Get name
                if name_cols:
                    name_parts = []
                    for name_col in name_cols:
                        if name_col in row and not pd.isna(row[name_col]):
                            name_parts.append(str(row[name_col]).strip())
                    full_name = ' '.join(name_parts) if name_parts else self.personalizer.extract_name_from_email(email)
                else:
                    full_name = self.personalizer.extract_name_from_email(email)
                
                # Validate email
                try:
                    validate_email(email)
                    result_data.append({'email': email, 'name': full_name})
                except EmailNotValidError:
                    continue
            
            if not result_data:
                st.error("❌ No valid emails found")
                return None
            
            return pd.DataFrame(result_data)
            
        except Exception as e:
            st.error(f"Error processing file: {e}")
            return None

# ================================
# CAMPAIGN GENERATOR
# ================================

def generate_campaign_blueprint(campaign_data):
    """Generate a campaign blueprint"""
    company_name = campaign_data.get('company_name', 'Your Company')
    campaign_type = campaign_data.get('campaign_type', 'Marketing Campaign')
    target_audience = campaign_data.get('target_audience', 'Target Audience')
    location = campaign_data.get('location', 'Global')
    channels = ', '.join(campaign_data.get('channels', ['Email']))
    budget = campaign_data.get('budget', 'TBD')
    currency = campaign_data.get('currency', 'USD')
    
    blueprint = f"""
# {company_name} - {campaign_type} Campaign Strategy

## 🎯 Campaign Overview
- **Company:** {company_name}
- **Campaign Type:** {campaign_type}
- **Target Market:** {location}
- **Budget:** {budget} {currency}
- **Channels:** {channels}

## 👥 Target Audience
{target_audience}

## 📈 Campaign Objectives
1. **Increase Brand Awareness** - Reach new potential customers
2. **Drive Engagement** - Generate meaningful interactions
3. **Boost Conversions** - Turn prospects into customers
4. **Build Customer Loyalty** - Strengthen relationships

## 🚀 Implementation Strategy

### Phase 1: Preparation (Week 1-2)
- Finalize creative assets and messaging
- Set up tracking and analytics
- Prepare email lists and segmentation
- Test all systems and workflows

### Phase 2: Launch (Week 3-4)
- Deploy campaigns across all channels
- Monitor performance in real-time
- Engage with audience responses
- Make quick optimizations as needed

### Phase 3: Optimization (Week 5-6)
- Analyze performance data
- A/B testing for improvement
- Scale successful elements
- Prepare follow-up campaigns

## 📊 Success Metrics
- **Reach:** Number of people exposed to campaign
- **Engagement:** Clicks, likes, shares, comments
- **Conversions:** Sign-ups, purchases, downloads
- **ROI:** Return on investment calculation

## 💰 Budget Allocation
- Creative Development: 25%
- Media/Advertising: 45%
- Technology & Tools: 20%
- Analytics & Reporting: 10%

## 🔄 Next Steps
1. Review and approve this strategy
2. Begin creative asset development
3. Set up tracking systems
4. Launch campaign according to timeline
5. Monitor and optimize performance

---
*Campaign strategy generated on {datetime.now().strftime('%Y-%m-%d')}*
"""
    
    return blueprint

def generate_email_template(campaign_type, tone, is_html=True):
    """Generate email template"""
    
    if is_html:
        template = f'''
<!DOCTYPE html>
<html>
<head>
    <title>{campaign_type}</title>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto; background-color: #f5f5f5; }}
        .container {{ background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px 20px; text-align: center; }}
        .content {{ padding: 30px 20px; line-height: 1.6; color: #333; }}
        .cta-button {{ background: #007bff; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; display: inline-block; margin: 20px 0; font-weight: bold; }}
        .footer {{ background: #f8f9fa; padding: 20px; text-align: center; font-size: 12px; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Hello {{first_name}}!</h1>
            <p>We have something special for you</p>
        </div>
        <div class="content">
            <p>Dear {{name}},</p>
            <p>We're excited to share this exclusive {campaign_type.lower()} with you.</p>
            <p>As a valued member of our community, you deserve the best we have to offer.</p>
            <div style="text-align: center;">
                <a href="#" class="cta-button">Discover More</a>
            </div>
            <p>Thank you for being part of our journey!</p>
        </div>
        <div class="footer">
            <p>Best regards,<br>The Marketing Team</p>
            <p>You received this email because you're subscribed to our updates.</p>
        </div>
    </div>
</body>
</html>
'''
    else:
        template = f'''Subject: Exclusive {campaign_type} for {{first_name}}

Hello {{first_name}},

We're excited to share this exclusive {campaign_type.lower()} with you.

As a valued member of our community, you deserve the best we have to offer.

Here's what makes this special:
• Personalized just for you
• Exclusive member benefits
• Limited-time opportunity
• Premium experience

Ready to explore? Visit our website or reply to this email.

Thank you for being part of our journey, {{name}}!

Best regards,
The Marketing Team

---
You received this email because you're subscribed to our updates.
Unsubscribe | Update Preferences'''
    
    return template

# ================================
# STREAMLIT APP
# ================================

st.set_page_config(
    page_title="Marketing Campaign Generator",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

initialize_session_state()

# Custom CSS
st.markdown("""
<style>
    .stApp {
        background: linear-gradient(135deg, #0f0f23 0%, #1a1a2e 100%);
        color: white;
    }
    h1, h2, h3 {
        color: #00d4ff !important;
    }
    .stButton > button {
        background: linear-gradient(45deg, #00d4ff, #0099cc) !important;
        color: white !important;
        border: none !important;
        border-radius: 10px !important;
        padding: 0.75rem 1.5rem !important;
        font-weight: 600 !important;
        width: 100% !important;
    }
</style>
""", unsafe_allow_html=True)

def main():
    # Header
    st.markdown("""
    <div style="text-align: center; padding: 2rem 0;">
        <h1 style="font-size: 3rem; margin-bottom: 0;">🚀 Marketing Campaign War Room</h1>
        <p style="font-size: 1.2rem; color: #888; margin-top: 0;">AI-Powered Campaign Generation & Email Marketing</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Navigation
    with st.sidebar:
        st.markdown("### 🎯 Navigation")
        
        if st.button("🎯 Campaign Dashboard"):
            st.session_state.current_page = "Campaign Dashboard"
            st.rerun()
        
        if st.button("📧 Email Marketing"):
            st.session_state.current_page = "Email Marketing"
            st.rerun()
        
        if st.button("📊 Analytics"):
            st.session_state.current_page = "Analytics"
            st.rerun()
        
        st.markdown("---")
        
        # System status
        st.markdown("### 🔧 System Status")
        
        if GMAIL_USER and GMAIL_PASSWORD:
            st.success("📧 Email: Connected")
        else:
            st.error("📧 Email: Not configured")
        
        if HF_TOKEN:
            st.success("🎨 Images: Connected")
        else:
            st.warning("🎨 Images: Not configured")
        
        # Campaign info
        if st.session_state.current_campaign:
            st.markdown("### 🎯 Active Campaign")
            st.info(f"**{st.session_state.current_campaign['company_name']}**")
        
        if st.session_state.email_contacts is not None:
            st.markdown("### 📊 Stats")
            st.info(f"📧 Contacts: {len(st.session_state.email_contacts)}")
    
    # Main content
    if st.session_state.current_page == "Campaign Dashboard":
        show_campaign_dashboard()
    elif st.session_state.current_page == "Email Marketing":
        show_email_marketing()
    elif st.session_state.current_page == "Analytics":
        show_analytics()

def show_campaign_dashboard():
    st.header("🎯 Campaign Strategy Generator")
    
    with st.form("campaign_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            company_name = st.text_input("🏢 Company Name")
            campaign_type = st.selectbox("📋 Campaign Type", [
                "Product Launch", "Brand Awareness", "Seasonal Campaign",
                "Lead Generation", "Customer Retention", "Event Promotion"
            ])
            target_audience = st.text_area("👥 Target Audience", 
                placeholder="Describe your target audience...")
            duration = st.text_input("📅 Duration", placeholder="e.g., 4 weeks")
        
        with col2:
            channels = st.multiselect("📢 Channels", [
                "Email Marketing", "Social Media", "Google Ads", "Facebook Ads",
                "Content Marketing", "Influencer Marketing"
            ])
            location = st.selectbox("🌍 Location", COUNTRIES)
            budget = st.text_input("💰 Budget", placeholder="e.g., 10000")
            currency = st.selectbox("💱 Currency", CURRENCIES)
        
        product_description = st.text_area("📦 Product/Service Description")
        
        col1, col2 = st.columns(2)
        with col1:
            generate_campaign = st.form_submit_button("🚀 Generate Campaign")
        with col2:
            generate_image = st.form_submit_button("🎨 Generate Image")
    
    if generate_campaign and company_name:
        campaign_data = {
            'company_name': company_name,
            'campaign_type': campaign_type,
            'target_audience': target_audience,
            'duration': duration,
            'channels': channels,
            'location': location,
            'budget': budget,
            'currency': currency,
            'product_description': product_description
        }
        
        with st.spinner("Generating campaign strategy..."):
            blueprint = generate_campaign_blueprint(campaign_data)
            st.session_state.current_campaign = campaign_data
            st.session_state.campaign_blueprint = blueprint
            st.success("✨ Campaign strategy generated!")
    
    if generate_image and st.session_state.current_campaign:
        campaign_desc = f"{st.session_state.current_campaign['company_name']} {st.session_state.current_campaign['campaign_type']}"
        image_gen = HuggingFaceImageGenerator()
        image_gen.generate_campaign_image(campaign_desc)
    
    if st.session_state.campaign_blueprint:
        st.markdown("---")
        st.markdown("## 📋 Campaign Strategy")
        st.markdown(st.session_state.campaign_blueprint)
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📧 Create Emails"):
                st.session_state.current_page = "Email Marketing"
                st.rerun()
        with col2:
            st.download_button("📄 Download", 
                data=st.session_state.campaign_blueprint,
                file_name=f"{st.session_state.current_campaign['company_name']}_strategy.md",
                mime="text/markdown")

def show_email_marketing():
    st.header("📧 Email Marketing Center")
    
    if st.session_state.current_campaign:
        st.success(f"🎯 Campaign: **{st.session_state.current_campaign['company_name']}**")
    
    # Email template generation
    st.subheader("🎨 Generate Email Template")
    
    col1, col2 = st.columns(2)
    with col1:
        email_type = st.selectbox("Email Type", [
            "Welcome", "Product Announcement", "Promotional Offer",
            "Newsletter", "Follow-up", "Event Invitation"
        ])
        tone = st.selectbox("Tone", ["Professional", "Friendly", "Casual", "Urgent"])
    
    with col2:
        content_format = st.radio("Format", ["HTML Template", "Plain Text"])
        
        if st.button("🚀 Generate Template"):
            is_html = content_format == "HTML Template"
            template = generate_email_template(email_type, tone, is_html)
            st.session_state.email_template = template
            st.success("✨ Template generated!")
    
    # Template editor
    if st.session_state.email_template:
        st.markdown("---")
        st.subheader("📝 Edit Email Template")
        
        edited_template = st.text_area("Email Content:", 
            value=st.session_state.email_template, 
            height=300)
        st.session_state.email_template = edited_template
        
        # Preview
        if st.button("👀 Preview") and 'html' in st.session_state.email_template.lower():
            personalizer = EmailPersonalizer()
            preview = personalizer.personalize_content(edited_template, "John Smith", "john@example.com")
            st.components.v1.html(preview, height=500, scrolling=True)
    
    st.markdown("---")
    
    # Contact upload
    st.subheader("👥 Upload Contacts")
    
    uploaded_file = st.file_uploader("Upload CSV/Excel", type=['csv', 'xlsx'])
    
    if uploaded_file:
        processor = FileProcessor()
        contacts = processor.process_file(uploaded_file)
        
        if contacts is not None:
            st.session_state.email_contacts = contacts
            st.success(f"✅ Loaded {len(contacts)} contacts!")
            st.dataframe(contacts)
    
    # WORKING Email campaign launch
    if (st.session_state.email_contacts is not None and 
        st.session_state.email_template):
        
        st.markdown("---")
        st.subheader("🚀 Launch Campaign")
        
        df = st.session_state.email_contacts
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("👥 Contacts", len(df))
        with col2:
            st.metric("📧 Template", "✅ Ready")
        with col3:
            st.metric("🔧 System", "✅ Ready")
        
        # Campaign settings
        subject = st.text_input("📧 Subject Line", 
            value="Hello {first_name}, check this out!")
        
        # Test email
        test_email = st.text_input("🧪 Test Email")
        if test_email and st.button("🧪 Send Test"):
            personalizer = EmailPersonalizer()
            test_content = personalizer.personalize_content(st.session_state.email_template, "Test User", test_email)
            test_subject = personalizer.personalize_content(subject, "Test User", test_email)
            
            # Simple test email send
            try:
                context = ssl.create_default_context()
                with smtplib.SMTP('smtp.gmail.com', 587) as server:
                    server.starttls(context=context)
                    server.login(GMAIL_USER, GMAIL_PASSWORD)
                    
                    msg = MIMEMultipart()
                    msg['Subject'] = f"[TEST] {test_subject}"
                    msg['From'] = GMAIL_USER
                    msg['To'] = test_email
                    msg.attach(MIMEText(test_content, 'html' if '<html>' in test_content.lower() else 'plain'))
                    
                    server.sendmail(GMAIL_USER, test_email, msg.as_string())
                    st.success("✅ Test email sent!")
            except Exception as e:
                st.error(f"❌ Test failed: {e}")
        
        # WORKING Launch button
        if st.button("🚀 LAUNCH EMAIL CAMPAIGN", type="primary"):
            st.warning(f"⚠️ About to send {len(df)} emails!")
            
            if st.button("✅ CONFIRM SEND"):
                # Create progress containers
                progress_placeholder = st.empty()
                status_placeholder = st.empty()
                
                # Send emails using the working function
                results = send_bulk_emails_working(
                    df, 
                    subject, 
                    st.session_state.email_template,
                    progress_placeholder,
                    status_placeholder
                )
                
                if not results.empty:
                    # Show results
                    success_count = len(results[results['status'] == 'sent'])
                    failed_count = len(results[results['status'] == 'failed'])
                    invalid_count = len(results[results['status'] == 'invalid'])
                    
                    st.markdown("### 🎉 Campaign Results")
                    
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("✅ Sent", success_count)
                    with col2:
                        st.metric("❌ Failed", failed_count)
                    with col3:
                        st.metric("⚠️ Invalid", invalid_count)
                    with col4:
                        success_rate = (success_count / len(results)) * 100
                        st.metric("📊 Success Rate", f"{success_rate:.1f}%")
                    
                    # Store results
                    st.session_state.campaign_results = results
                    
                    # Download results
                    csv = results.to_csv(index=False)
                    st.download_button("📥 Download Results", 
                        data=csv, 
                        file_name=f"results_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                        mime="text/csv")
                    
                    # Show detailed results
                    with st.expander("📋 View Results"):
                        st.dataframe(results)
                    
                    if success_count > 0:
                        st.balloons()

def show_analytics():
    st.header("📊 Analytics Dashboard")
    
    if st.session_state.current_campaign:
        campaign = st.session_state.current_campaign
        location = campaign['location']
        
        if location in COUNTRIES_DATA:
            coords = COUNTRIES_DATA[location]['coords']
            
            # Create map
            map_data = pd.DataFrame({
                'lat': [coords[0]],
                'lon': [coords[1]], 
                'location': [location]
            })
            
            fig = px.scatter_mapbox(
                map_data,
                lat='lat',
                lon='lon',
                hover_name='location',
                color_discrete_sequence=['#00d4ff'],
                zoom=3,
                title=f"Campaign Target: {location}"
            )
            
            fig.update_layout(
                mapbox_style="carto-darkmatter",
                template="plotly_dark",
                height=400
            )
            
            st.plotly_chart(fig, use_container_width=True)
    
    # Email results
    if st.session_state.campaign_results is not None:
        st.subheader("📧 Email Campaign Results")
        
        results_df = st.session_state.campaign_results
        
        # Metrics
        total_sent = len(results_df[results_df['status'] == 'sent'])
        total_failed = len(results_df[results_df['status'] == 'failed'])
        success_rate = (total_sent / len(results_df)) * 100
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("📧 Total", len(results_df))
        with col2:
            st.metric("✅ Sent", total_sent)
        with col3:
            st.metric("📊 Success Rate", f"{success_rate:.1f}%")
        
        # Results pie chart
        status_counts = results_df['status'].value_counts()
        fig = px.pie(values=status_counts.values, names=status_counts.index,
                    title="Email Results", 
                    color_discrete_map={'sent': '#28a745', 'failed': '#dc3545', 'invalid': '#ffc107'})
        fig.update_layout(template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    main()

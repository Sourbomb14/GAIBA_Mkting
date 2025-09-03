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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Load environment variables
load_dotenv()

# Configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

# ================================
# UTILITY CLASSES AND FUNCTIONS
# ================================

class EmailPersonalizer:
    """Handle intelligent email personalization"""
    
    @staticmethod
    def extract_name_from_email(email):
        """Extract potential name from email address"""
        try:
            local_part = email.split('@')[0]
            # Remove numbers and special characters
            name_part = re.sub(r'[0-9._-]', ' ', local_part)
            # Split and capitalize
            name_parts = [part.capitalize() for part in name_part.split() if len(part) > 1]
            return ' '.join(name_parts) if name_parts else 'Valued Customer'
        except:
            return 'Valued Customer'
    
    @staticmethod
    def personalize_template(template, name, email=None):
        """Personalize email template with various name formats"""
        first_name = name.split()[0] if name and ' ' in name else name
        
        # Replace various name placeholders
        personalized = template.replace('{name}', name or 'Valued Customer')
        personalized = personalized.replace('{{name}}', name or 'Valued Customer')
        personalized = personalized.replace('{first_name}', first_name or 'Valued Customer')
        personalized = personalized.replace('{{first_name}}', first_name or 'Valued Customer')
        personalized = personalized.replace('{email}', email or '')
        personalized = personalized.replace('{{email}}', email or '')
        
        return personalized

class EmailHandler:
    """Handle email operations with proper threading"""
    
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
        """Send a single email"""
        if not self.email or not self.password:
            return False, "Email configuration missing"
            
        try:
            msg = MIMEMultipart()
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
                server.send_message(msg)
            
            return True, "Success"
        except Exception as e:
            return False, str(e)
    
    def send_email_batch(self, email_batch, subject, body_template, personalizer):
        """Send a batch of emails"""
        results = []
        
        for _, row in email_batch.iterrows():
            if self.validate_email_address(row['email']):
                # Personalize the email
                personalized_body = personalizer.personalize_template(
                    body_template, 
                    row.get('name', 'Valued Customer'), 
                    row['email']
                )
                personalized_subject = personalizer.personalize_template(
                    subject,
                    row.get('name', 'Valued Customer'),
                    row['email']
                )
                
                success, error_msg = self.send_single_email(
                    row['email'], 
                    personalized_subject, 
                    personalized_body, 
                    is_html=True
                )
                
                results.append({
                    "email": row['email'],
                    "name": row.get('name', 'Valued Customer'),
                    "status": "sent" if success else "failed",
                    "error": error_msg if not success else ""
                })
                
                # Small delay between emails
                time.sleep(1)
            else:
                results.append({
                    "email": row['email'],
                    "name": row.get('name', 'Valued Customer'),
                    "status": "invalid",
                    "error": "Invalid email format"
                })
        
        return results
    
    def send_bulk_emails(self, email_list, subject, body_template, personalizer, batch_size=10):
        """Send bulk emails with proper threading and progress tracking"""
        if not self.email or not self.password:
            st.error("❌ Email configuration missing. Please check your .env file.")
            return pd.DataFrame()
        
        total_emails = len(email_list)
        all_results = []
        
        # Create progress components
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # Real-time metrics
        metrics_container = st.container()
        with metrics_container:
            col1, col2, col3, col4 = st.columns(4)
            sent_metric = col1.metric("✅ Sent", 0)
            failed_metric = col2.metric("❌ Failed", 0)
            invalid_metric = col3.metric("⚠️ Invalid", 0)
            progress_metric = col4.metric("📊 Progress", "0%")
        
        sent_count = 0
        failed_count = 0
        invalid_count = 0
        
        # Process in batches
        for i in range(0, total_emails, batch_size):
            batch = email_list.iloc[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (total_emails + batch_size - 1) // batch_size
            
            status_text.text(f"📧 Sending batch {batch_num} of {total_batches}...")
            
            # Send batch
            batch_results = self.send_email_batch(batch, subject, body_template, personalizer)
            all_results.extend(batch_results)
            
            # Update counters
            for result in batch_results:
                if result['status'] == 'sent':
                    sent_count += 1
                elif result['status'] == 'failed':
                    failed_count += 1
                elif result['status'] == 'invalid':
                    invalid_count += 1
            
            # Update progress
            progress = (i + len(batch)) / total_emails
            progress_bar.progress(progress)
            
            # Update metrics
            with metrics_container:
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("✅ Sent", sent_count)
                col2.metric("❌ Failed", failed_count)
                col3.metric("⚠️ Invalid", invalid_count)
                col4.metric("📊 Progress", f"{progress * 100:.1f}%")
            
            # Delay between batches
            if i + batch_size < total_emails:
                time.sleep(2)
        
        progress_bar.progress(1.0)
        status_text.text("🎉 Campaign completed!")
        
        return pd.DataFrame(all_results)

class FileProcessor:
    """Handle file processing for contact extraction"""
    
    def __init__(self):
        self.email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    
    def extract_emails_from_text(self, text):
        """Extract email addresses from plain text"""
        emails = re.findall(self.email_pattern, text)
        return list(set(emails))
    
    def validate_email_list(self, emails):
        """Validate a list of email addresses"""
        valid_emails = []
        invalid_emails = []
        
        for email in emails:
            try:
                validate_email(email)
                valid_emails.append(email)
            except EmailNotValidError:
                invalid_emails.append(email)
        
        return valid_emails, invalid_emails
    
    def process_csv(self, file):
        """Process CSV file"""
        try:
            df = pd.read_csv(file)
            return self._standardize_dataframe(df)
        except Exception as e:
            st.error(f"Error reading CSV file: {e}")
            return None
    
    def process_excel(self, file):
        """Process Excel file"""
        try:
            df = pd.read_excel(file)
            return self._standardize_dataframe(df)
        except Exception as e:
            st.error(f"Error reading Excel file: {e}")
            return None
    
    def _standardize_dataframe(self, df):
        """Standardize dataframe columns"""
        # Convert all column names to lowercase
        df.columns = df.columns.str.lower()
        
        # Try to find email column
        email_col = None
        name_col = None
        
        # Look for email column
        for col in df.columns:
            if 'email' in col or 'mail' in col:
                email_col = col
                break
        
        # Look for name column
        for col in df.columns:
            if 'name' in col or 'first' in col or 'last' in col:
                name_col = col
                break
        
        if email_col is None:
            # If no email column found, try to extract from all columns
            all_text = df.astype(str).values.flatten()
            emails = []
            for text in all_text:
                emails.extend(self.extract_emails_from_text(text))
            
            if emails:
                return pd.DataFrame({
                    'email': list(set(emails)),
                    'name': ['Contact'] * len(set(emails))
                })
            else:
                st.error("No email addresses found in the file")
                return None
        
        # Create standardized dataframe
        result_df = pd.DataFrame()
        result_df['email'] = df[email_col]
        
        if name_col:
            result_df['name'] = df[name_col]
        else:
            result_df['name'] = 'Contact'
        
        # Remove rows with empty emails
        result_df = result_df.dropna(subset=['email'])
        result_df = result_df[result_df['email'].str.strip() != '']
        
        # Validate emails
        valid_emails, invalid_emails = self.validate_email_list(result_df['email'].tolist())
        
        if invalid_emails:
            st.warning(f"Found {len(invalid_emails)} invalid email addresses that will be excluded")
        
        # Keep only valid emails
        result_df = result_df[result_df['email'].isin(valid_emails)]
        
        return result_df

class CampaignGenerator:
    """Generate campaign content using Groq API"""
    
    def __init__(self):
        self.client = None
        if GROQ_API_KEY:
            try:
                self.client = Groq(api_key=GROQ_API_KEY)
            except Exception as e:
                st.error(f"Failed to initialize Groq client: {e}")
    
    def generate_campaign_blueprint(self, campaign_data):
        """Generate campaign blueprint using Groq API"""
        if not self.client:
            return self._fallback_campaign_blueprint(campaign_data)
        
        try:
            company_name = campaign_data.get('company_name', 'Your Company')
            campaign_type = campaign_data.get('campaign_type', 'Marketing Campaign')
            target_audience = campaign_data.get('target_audience', 'General audience')
            channels = ', '.join(campaign_data.get('channels', ['Email']))
            location = campaign_data.get('location', 'Global')
            budget = campaign_data.get('budget', 'Not specified')
            product_description = campaign_data.get('product_description', 'Product/Service')
            
            prompt = f"""
            Create a comprehensive marketing campaign blueprint for {company_name}.
            
            Campaign Details:
            - Campaign Type: {campaign_type}
            - Target Audience: {target_audience}
            - Marketing Channels: {channels}
            - Geographic Location: {location}
            - Budget: {budget}
            - Product/Service: {product_description}
            
            Please provide a detailed campaign blueprint including:
            1. Executive Summary
            2. Campaign Objectives (SMART goals)
            3. Target Audience Analysis (demographics, psychographics, pain points)
            4. Key Messages & Value Proposition
            5. Marketing Channels Strategy (specific tactics for each channel)
            6. Campaign Timeline (pre-launch, launch, post-launch phases)
            7. Budget Allocation (breakdown by channel and activity)
            8. Success Metrics & KPIs (specific, measurable metrics)
            9. Risk Assessment & Mitigation Strategies
            10. Call-to-Action Strategy
            
            Make it professional, actionable, and tailored to the specific business and audience.
            """
            
            response = self.client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert marketing strategist with 15+ years of experience creating successful marketing campaigns. Provide detailed, actionable, and professional marketing strategies."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                model="mixtral-8x7b-32768",
                temperature=0.7,
                max_tokens=4000
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            st.error(f"Error generating campaign with Groq API: {e}")
            return self._fallback_campaign_blueprint(campaign_data)
    
    def generate_email_template(self, campaign_brief, tone="professional"):
        """Generate email template using Groq API"""
        if not self.client:
            return self._fallback_email_template()
        
        try:
            prompt = f"""
            Create a professional HTML email template based on this campaign brief:
            {campaign_brief}
            
            Requirements:
            - Tone: {tone}
            - Include proper HTML structure with inline CSS
            - Make it mobile-responsive
            - Include personalization placeholders: {{{{first_name}}}}, {{{{name}}}}
            - Include a clear call-to-action button
            - Add professional styling with modern design
            - Include header, body content, CTA, and footer sections
            - Use a color scheme that's professional and engaging
            - Make sure it works well in email clients
            
            The email should be engaging, conversion-focused, and brand-appropriate.
            """
            
            response = self.client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert email marketing designer. Create professional, conversion-optimized HTML email templates that work across all email clients."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                model="mixtral-8x7b-32768",
                temperature=0.6,
                max_tokens=3000
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            st.error(f"Error generating email template with Groq API: {e}")
            return self._fallback_email_template()
    
    def _fallback_campaign_blueprint(self, campaign_data):
        """Fallback campaign blueprint when API is not available"""
        company_name = campaign_data.get('company_name', 'Your Company')
        campaign_type = campaign_data.get('campaign_type', 'Marketing Campaign')
        target_audience = campaign_data.get('target_audience', 'General audience')
        channels = ', '.join(campaign_data.get('channels', ['Email']))
        
        return f"""
# {company_name} - {campaign_type} Campaign Blueprint

## Executive Summary
This {campaign_type.lower()} campaign for {company_name} is designed to engage {target_audience} through strategic messaging across {channels}.

## Campaign Objectives
- Increase brand awareness and market presence
- Drive qualified leads and conversions
- Build customer loyalty and retention
- Expand market reach in target segments
- Achieve measurable ROI and business growth

## Target Audience Analysis
**Primary Audience:** {target_audience}
- Demographics: Based on provided audience description
- Psychographics: Interests, values, and behaviors aligned with campaign goals
- Pain Points: Challenges our product/service can solve
- Channel Preferences: {channels}
- Decision-making process and buyer journey considerations

## Key Messages & Value Proposition
- **Primary Message:** Clear value proposition highlighting unique benefits
- **Supporting Messages:** Feature-specific benefits and social proof
- **Emotional Appeal:** Connect with audience's aspirations and pain points
- **Differentiation:** What sets us apart from competitors
- **Call-to-Action:** Clear, compelling action for prospects to take

## Marketing Channels Strategy
**Selected Channels:** {channels}

**Email Marketing:**
- Segmented campaigns based on audience personas
- Automated drip sequences for nurturing leads
- Personalized content based on user behavior
- A/B testing for subject lines and content

**Additional Channels:**
- Social Media: Community building and brand awareness
- Content Marketing: Educational and thought leadership content
- Paid Advertising: Targeted campaigns for lead generation

## Campaign Timeline

**Phase 1 - Pre-Launch (Weeks 1-2)**
- Finalize creative assets and copy
- Set up tracking and analytics
- Prepare email lists and segmentation
- Conduct final testing and quality assurance

**Phase 2 - Launch (Weeks 3-4)**
- Deploy campaigns across all channels
- Monitor performance and optimize in real-time
- Respond to customer inquiries and feedback
- Adjust targeting and messaging based on early results

**Phase 3 - Post-Launch (Weeks 5-6)**
- Analyze performance data and generate insights
- Conduct follow-up campaigns for non-converters
- Gather customer feedback and testimonials
- Plan next phase or follow-up campaigns

## Success Metrics (KPIs)
- **Email Marketing:** Open rates (25%+), Click rates (3%+), Conversion rates (2%+)
- **Lead Generation:** Cost per lead, Lead quality score, Lead-to-customer conversion
- **Revenue:** Return on ad spend (ROAS), Customer acquisition cost (CAC)
- **Engagement:** Social media engagement, Website traffic, Content consumption

## Budget Allocation
- Creative Development: 25%
- Media/Advertising Spend: 45%
- Technology and Tools: 15%
- Analytics and Reporting: 10%
- Contingency Fund: 5%

## Risk Assessment & Mitigation
- **Low Engagement Risk:** Mitigate with A/B testing and audience research
- **Technical Issues:** Have backup systems and redundancy plans
- **Competitive Response:** Monitor competitor activities and be ready to adapt
- **Budget Overruns:** Regular monitoring and approval processes for additional spend

## Next Steps
1. Approve campaign strategy and budget
2. Begin creative asset development
3. Set up tracking and measurement systems
4. Finalize audience lists and targeting
5. Launch campaign according to timeline
"""
    
    def _fallback_email_template(self):
        """Fallback email template when API is not available"""
        return '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Campaign Email</title>
    <style>
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            line-height: 1.6; 
            color: #333; 
            max-width: 600px; 
            margin: 0 auto; 
            padding: 0; 
            background-color: #f4f4f4;
        }
        .email-container {
            background-color: #ffffff;
            margin: 20px auto;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        .header { 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white; 
            padding: 30px 20px; 
            text-align: center; 
        }
        .header h1 {
            margin: 0;
            font-size: 28px;
            font-weight: 600;
        }
        .content { 
            padding: 40px 30px; 
            background-color: #ffffff;
        }
        .content h2 {
            color: #333;
            font-size: 24px;
            margin-bottom: 20px;
        }
        .content p {
            margin-bottom: 16px;
            color: #555;
            font-size: 16px;
        }
        .cta-button { 
            background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
            color: white !important; 
            padding: 15px 30px; 
            text-decoration: none; 
            border-radius: 6px; 
            display: inline-block; 
            margin: 25px 0; 
            font-weight: 600;
            font-size: 16px;
            text-align: center;
            transition: transform 0.2s ease;
        }
        .cta-button:hover {
            transform: translateY(-2px);
        }
        .features {
            background-color: #f8f9fa;
            padding: 20px;
            border-radius: 6px;
            margin: 20px 0;
        }
        .features ul {
            margin: 0;
            padding-left: 20px;
        }
        .features li {
            margin-bottom: 8px;
            color: #555;
        }
        .footer { 
            text-align: center; 
            padding: 30px 20px; 
            background-color: #f8f9fa;
            border-top: 1px solid #dee2e6;
            color: #6c757d;
        }
        .footer p {
            margin: 5px 0;
            font-size: 14px;
        }
        .footer a {
            color: #667eea;
            text-decoration: none;
        }
        @media only screen and (max-width: 600px) {
            .email-container {
                margin: 0;
                border-radius: 0;
            }
            .content {
                padding: 20px 15px;
            }
            .header {
                padding: 20px 15px;
            }
        }
    </style>
</head>
<body>
    <div class="email-container">
        <div class="header">
            <h1>🚀 Exciting News Awaits!</h1>
        </div>
        
        <div class="content">
            <h2>Hello {{first_name}},</h2>
            
            <p>We hope this message finds you well! We're thrilled to share something special that we believe will make a real difference for you.</p>
            
            <p>As someone who values innovation and quality, we thought you'd be excited to learn about our latest campaign. We've been working tirelessly to bring you an experience that's tailored exactly to what you need.</p>
            
            <div class="features">
                <p><strong>Here's what makes this opportunity special:</strong></p>
                <ul>
                    <li>✨ Personalized experience designed with you in mind</li>
                    <li>🎯 Exclusive benefits for our valued community members</li>
                    <li>⏰ Limited-time opportunity to be among the first</li>
                    <li>🔒 Backed by our commitment to quality and results</li>
                </ul>
            </div>
            
            <p>We believe this will bring significant value to your experience with us, and we can't wait for you to see what we've prepared.</p>
            
            <center>
                <a href="https://example.com/campaign" class="cta-button">Discover What's New →</a>
            </center>
            
            <p>Thank you for being such an important part of our community. Your trust and support mean everything to us, and we're excited to continue this journey together.</p>
            
            <p>Best regards,<br>
            <strong>The Team</strong><br>
            <em>Your Company Name</em></p>
        </div>
        
        <div class="footer">
            <p>You received this email because you're a valued member of our community.</p>
            <p>
                <a href="#unsubscribe">Unsubscribe</a> | 
                <a href="#preferences">Email Preferences</a> | 
                <a href="#contact">Contact Us</a>
            </p>
            <p>© 2024 Your Company Name. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
'''

# ================================
# STREAMLIT APP CONFIGURATION
# ================================

st.set_page_config(
    page_title="Marketing Campaign Generator",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for modern dark theme
st.markdown("""
<style>
    /* Import modern font */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    /* Main theme */
    .stApp {
        background: linear-gradient(135deg, #0f0f23 0%, #1a1a2e 100%);
        font-family: 'Inter', sans-serif;
    }
    
    /* Sidebar styling */
    .css-1d391kg {
        background: linear-gradient(180deg, #16213e 0%, #0f3460 100%);
    }
    
    /* Headers */
    h1, h2, h3 {
        color: #00d4ff !important;
        font-weight: 600 !important;
    }
    
    /* Buttons */
    .stButton > button {
        background: linear-gradient(45deg, #00d4ff, #0099cc);
        color: white;
        border: none;
        border-radius: 10px;
        padding: 0.5rem 1.5rem;
        font-weight: 600;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(0, 212, 255, 0.3);
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(0, 212, 255, 0.4);
    }
    
    /* Input fields */
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea,
    .stSelectbox > div > div > select {
        background-color: #1e1e1e !important;
        color: #ffffff !important;
        border: 1px solid #333 !important;
        border-radius: 8px !important;
    }
    
    /* Success/Error messages */
    .stSuccess {
        background-color: #1a4d3a !important;
        border: 1px solid #28a745 !important;
        border-radius: 8px !important;
    }
    
    .stError {
        background-color: #4d1a1a !important;
        border: 1px solid #dc3545 !important;
        border-radius: 8px !important;
    }
    
    .stWarning {
        background-color: #4d3a1a !important;
        border: 1px solid #ffc107 !important;
        border-radius: 8px !important;
    }
</style>
""", unsafe_allow_html=True)

# ================================
# MAIN APPLICATION
# ================================

def main():
    # Initialize session state
    if 'page' not in st.session_state:
        st.session_state.page = "Campaign Dashboard"
    
    # Header
    st.markdown("""
    <div style="text-align: center; padding: 2rem 0;">
        <h1 style="font-size: 3rem; margin-bottom: 0;">🚀 Marketing Campaign War Room</h1>
        <p style="font-size: 1.2rem; color: #888; margin-top: 0;">AI-Powered Campaign Generation & Email Marketing Platform</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Ethical Disclaimer
    with st.expander("⚠️ ETHICAL USE DISCLAIMER - PLEASE READ"):
        st.warning("""
        **IMPORTANT: Ethical Use Policy**
        
        This application is designed for legitimate marketing purposes only. By using this tool, you agree to:
        
        ✅ **DO:**
        - Only send emails to people who have explicitly opted in to receive communications
        - Respect unsubscribe requests immediately
        - Comply with GDPR, CAN-SPAM Act, and other applicable laws
        - Use accurate sender information and clear subject lines
        - Provide valuable, relevant content to recipients
        
        ❌ **DON'T:**
        - Send unsolicited spam emails
        - Use purchased or scraped email lists without consent
        - Mislead recipients with false subject lines or sender information
        - Send emails for illegal or unethical purposes
        - Ignore data protection regulations
        
        **Legal Responsibility:** Users are solely responsible for compliance with all applicable laws and regulations. 
        This tool does not provide legal advice. Consult with legal counsel for compliance guidance.
        
        **Data Privacy:** Ensure all personal data is handled in accordance with applicable privacy laws.
        """)
    
    # Navigation
    with st.sidebar:
        st.markdown("### 🎯 Navigation")
        
        page = st.radio(
            "Choose Module:",
            ["🎯 Campaign Dashboard", "📧 Email Marketing", "📊 Analytics & Reports"],
            key="main_nav"
        )
        
        st.markdown("---")
        
        # System status
        st.markdown("### 🔧 System Status")
        
        if GROQ_API_KEY:
            st.success("🤖 AI Engine: Connected")
        else:
            st.warning("🤖 AI Engine: Not configured")
        
        if GMAIL_USER and GMAIL_APP_PASSWORD:
            st.success("📧 Email Service: Connected")
        else:
            st.error("📧 Email Service: Not configured")
        
        st.markdown("---")
        
        # Quick stats
        if 'email_contacts' in st.session_state:
            st.markdown("### 📊 Quick Stats")
            st.info(f"📧 Contacts loaded: {len(st.session_state['email_contacts'])}")
        
        if 'current_campaign' in st.session_state:
            st.info(f"🎯 Active campaign: {st.session_state['current_campaign']['company_name']}")
    
    # Main content based on navigation
    if page == "🎯 Campaign Dashboard":
        show_campaign_dashboard()
    elif page == "📧 Email Marketing":
        show_email_marketing()
    elif page == "📊 Analytics & Reports":
        show_analytics_reports()

def show_campaign_dashboard():
    st.header("🎯 AI-Powered Campaign Strategy Generator")
    
    with st.form("campaign_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            company_name = st.text_input("🏢 Company Name", placeholder="Enter your company name")
            campaign_type = st.selectbox("📋 Campaign Type", [
                "Product Launch",
                "Brand Awareness", 
                "Seasonal Campaign",
                "Customer Retention",
                "Lead Generation",
                "Event Promotion",
                "Sales Campaign",
                "Newsletter Campaign"
            ])
            target_audience = st.text_area("👥 Target Audience", 
                placeholder="Describe your target audience (demographics, interests, etc.)")
            duration = st.text_input("📅 Campaign Duration", 
                placeholder="e.g., 4 weeks, 2 months")
        
        with col2:
            channels = st.multiselect("📢 Marketing Channels", [
                "Email Marketing",
                "Social Media",
                "Google Ads",
                "Facebook Ads",
                "Content Marketing",
                "Influencer Marketing",
                "TV/Radio",
                "Print Media",
                "Events/Webinars"
            ])
            location = st.text_input("🌍 Geographic Location", 
                placeholder="e.g., Global, United States, California")
            customer_segment = st.selectbox("💼 Customer Segment",
                ["Mass Market", "Premium", "Niche", "Enterprise", "SMB"])
            budget = st.text_input("💰 Budget (Optional)",
                placeholder="e.g., $10,000 USD")
        
        product_description = st.text_area("📦 Product/Service Description",
            placeholder="Describe what you're promoting in this campaign...")
        
        submitted = st.form_submit_button("🚀 Generate AI Campaign Blueprint", 
            use_container_width=True)
    
    if submitted and company_name and campaign_type:
        campaign_data = {
            'company_name': company_name,
            'campaign_type': campaign_type,
            'target_audience': target_audience,
            'duration': duration,
            'channels': channels,
            'location': location,
            'customer_segment': customer_segment,
            'budget': budget,
            'product_description': product_description
        }
        
        with st.spinner("🤖 AI is analyzing your requirements and generating a comprehensive campaign strategy..."):
            generator = CampaignGenerator()
            blueprint = generator.generate_campaign_blueprint(campaign_data)
            
            st.session_state['current_campaign'] = campaign_data
            st.session_state['campaign_blueprint'] = blueprint
            
            st.success("✨ AI-powered campaign blueprint generated successfully!")
            st.balloons()
            
            # Display blueprint
            st.markdown("## 📋 Your AI-Generated Campaign Blueprint")
            st.markdown(blueprint)
            
            # Action buttons
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("📧 Create Email Campaign", use_container_width=True):
                    st.session_state.page = "📧 Email Marketing"
                    st.rerun()
            with col2:
                if st.button("📊 View Analytics", use_container_width=True):
                    st.session_state.page = "📊 Analytics & Reports"
                    st.rerun()
            with col3:
                st.download_button("📄 Download Blueprint", 
                    data=blueprint, 
                    file_name=f"{company_name}_campaign_blueprint.md",
                    mime="text/markdown",
                    use_container_width=True)
    
    elif submitted:
        st.error("⚠️ Please fill in at least Company Name and Campaign Type")

def show_email_marketing():
    st.header("📧 AI Email Marketing Center")
    
    email_handler = EmailHandler()
    personalizer = EmailPersonalizer()
    file_processor = FileProcessor()
    
    # Check for active campaign
    if 'current_campaign' in st.session_state:
        st.success(f"🎯 Active Campaign: **{st.session_state['current_campaign']['company_name']}**")
    
    # Email Template Generation
    st.subheader("🎨 AI Email Template Generator")
    
    template_col1, template_col2 = st.columns(2)
    
    with template_col1:
        email_type = st.selectbox("📧 Email Type", [
            "Welcome Email",
            "Product Announcement", 
            "Promotional Offer",
            "Newsletter",
            "Follow-up Email",
            "Event Invitation",
            "Customer Survey"
        ])
        tone = st.selectbox("🎭 Tone", ["Professional", "Friendly", "Casual", "Urgent", "Formal"])
    
    with template_col2:
        if st.button("🚀 Generate AI Email Template", type="primary"):
            if 'current_campaign' in st.session_state:
                campaign_brief = st.session_state.get('campaign_blueprint', 'Marketing campaign')
                generator = CampaignGenerator()
                
                with st.spinner("🤖 AI is crafting your personalized email template..."):
                    template = generator.generate_email_template(campaign_brief, tone.lower())
                    st.session_state['email_template'] = template
                    st.success("✨ AI email template generated successfully!")
            else:
                st.warning("⚠️ Please create a campaign first")
    
    # Template Editor and Preview
    if 'email_template' in st.session_state:
        st.markdown("---")
        st.subheader("📝 Email Template Editor")
        
        # HTML Editor
        edited_template = st.text_area(
            "Edit your email template:",
            value=st.session_state['email_template'],
            height=300,
            help="Use {first_name}, {name}, and {email} for personalization"
        )
        
        if edited_template != st.session_state['email_template']:
            st.session_state['email_template'] = edited_template
        
        # Preview
        if st.button("👀 Preview Template"):
            preview_name = "John Smith"
            preview_email = "john.smith@example.com"
            
            preview_template = personalizer.personalize_template(
                st.session_state['email_template'], 
                preview_name, 
                preview_email
            )
            
            st.markdown("### 📧 Email Preview")
            st.components.v1.html(preview_template, height=500, scrolling=True)
    
    st.markdown("---")
    
    # Contact Import
    st.subheader("👥 Import Email Contacts")
    
    import_tab1, import_tab2 = st.tabs(["📁 File Upload", "✍️ Manual Entry"])
    
    with import_tab1:
        uploaded_file = st.file_uploader(
            "Upload contact file",
            type=['csv', 'xlsx'],
            help="Upload CSV or Excel file with email addresses"
        )
        
        if uploaded_file:
            file_extension = uploaded_file.name.split('.')[-1].lower()
            
            with st.spinner("Processing file..."):
                if file_extension == 'csv':
                    df = file_processor.process_csv(uploaded_file)
                else:
                    df = file_processor.process_excel(uploaded_file)
                
                if df is not None and not df.empty:
                    # Add intelligent name extraction
                    if 'name' not in df.columns or df['name'].isna().all():
                        df['name'] = df['email'].apply(personalizer.extract_name_from_email)
                    
                    st.success(f"✅ Loaded {len(df)} contacts successfully!")
                    st.session_state['email_contacts'] = df
                    
                    # Show preview
                    st.dataframe(df, use_container_width=True)
    
    with import_tab2:
        manual_emails = st.text_area(
            "Enter email addresses (one per line):",
            placeholder="john@example.com\njane@company.com\nbob@business.org",
            height=150
        )
        
        if st.button("Process Emails") and manual_emails:
            emails = [email.strip() for email in manual_emails.split('\n') if email.strip()]
            valid_emails, invalid_emails = file_processor.validate_email_list(emails)
            
            if valid_emails:
                df = pd.DataFrame({
                    'email': valid_emails,
                    'name': [personalizer.extract_name_from_email(email) for email in valid_emails]
                })
                
                st.session_state['email_contacts'] = df
                st.success(f"✅ Added {len(valid_emails)} valid contacts!")
                
                if invalid_emails:
                    st.warning(f"⚠️ Excluded {len(invalid_emails)} invalid emails")
                
                st.dataframe(df, use_container_width=True)
    
    # Email Campaign
    if 'email_contacts' in st.session_state and 'email_template' in st.session_state:
        st.markdown("---")
        st.subheader("🚀 Launch Email Campaign")
        
        df = st.session_state['email_contacts']
        
        # Campaign metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("👥 Total Contacts", len(df))
        with col2:
            st.metric("✅ Valid Emails", len(df['email'].dropna()))
        with col3:
            domains = df['email'].str.split('@').str[1].nunique()
            st.metric("🏢 Unique Domains", domains)
        with col4:
            st.metric("📧 Template Status", "✅ Ready")
        
        # Campaign configuration
        campaign_col1, campaign_col2 = st.columns(2)
        
        with campaign_col1:
            subject = st.text_input("📧 Email Subject", 
                value="Important Update from Our Team")
            sender_name = st.text_input("👤 Sender Name", 
                value="Marketing Team")
        
        with campaign_col2:
            test_email = st.text_input("🧪 Test Email (Optional)", 
                placeholder="your-email@example.com")
            batch_size = st.number_input("📦 Batch Size", 
                min_value=1, max_value=50, value=10,
                help="Number of emails to send in each batch")
        
        # Test email
        if test_email and st.button("🧪 Send Test Email"):
            test_template = personalizer.personalize_template(
                st.session_state['email_template'], 
                "Test User", 
                test_email
            )
            
            success, error_msg = email_handler.send_single_email(
                test_email, 
                f"[TEST] {subject}", 
                test_template, 
                is_html=True
            )
            
            if success:
                st.success("✅ Test email sent successfully!")
            else:
                st.error(f"❌ Failed to send test email: {error_msg}")
        
        # Launch campaign
        st.markdown("### 🎯 Campaign Launch")
        
        if st.button("🚀 LAUNCH EMAIL CAMPAIGN", type="primary", use_container_width=True):
            if not GMAIL_USER or not GMAIL_APP_PASSWORD:
                st.error("❌ Email configuration missing. Please check your .env file.")
                return
            
            st.warning("⚠️ You are about to send emails to all contacts. This cannot be undone!")
            
            if st.button("✅ CONFIRM LAUNCH"):
                with st.spinner("📧 Launching email campaign..."):
                    results = email_handler.send_bulk_emails(
                        df, subject, st.session_state['email_template'], personalizer, batch_size
                    )
                    
                    if not results.empty:
                        # Show results
                        success_count = len(results[results['status'] == 'sent'])
                        failed_count = len(results[results['status'] == 'failed'])
                        invalid_count = len(results[results['status'] == 'invalid'])
                        
                        st.success("🎉 Campaign completed!")
                        
                        result_col1, result_col2, result_col3 = st.columns(3)
                        
                        with result_col1:
                            st.metric("✅ Sent", success_count)
                        with result_col2:
                            st.metric("❌ Failed", failed_count)
                        with result_col3:
                            st.metric("⚠️ Invalid", invalid_count)
                        
                        # Store results for analytics
                        st.session_state['campaign_results'] = results
                        
                        # Download results
                        csv = results.to_csv(index=False)
                        st.download_button(
                            "📥 Download Results",
                            data=csv,
                            file_name=f"campaign_results_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                            mime="text/csv"
                        )
                        
                        # Show detailed results
                        with st.expander("📋 View Detailed Results"):
                            st.dataframe(results, use_container_width=True)
    
    # Quick single email
    st.markdown("---")
    st.subheader("📧 Quick Single Email")
    
    with st.form("single_email_form"):
        single_col1, single_col2 = st.columns(2)
        
        with single_col1:
            recipient = st.text_input("📧 Recipient Email")
            recipient_name = st.text_input("👤 Recipient Name (Optional)")
        
        with single_col2:
            single_subject = st.text_input("📝 Subject")
            use_template = st.checkbox("Use Generated Template", 
                value='email_template' in st.session_state)
        
        if use_template and 'email_template' in st.session_state:
            body = st.text_area("📧 Email Body (Template)", 
                value=st.session_state['email_template'], height=200)
        else:
            body = st.text_area("📧 Email Body", height=200)
        
        if st.form_submit_button("📧 Send Email", use_container_width=True):
            if recipient and single_subject and body:
                final_name = recipient_name if recipient_name else personalizer.extract_name_from_email(recipient)
                final_body = personalizer.personalize_template(body, final_name, recipient)
                
                success, error_msg = email_handler.send_single_email(recipient, single_subject, final_body, is_html=True)
                
                if success:
                    st.success(f"✅ Email sent to {final_name} ({recipient})!")
                else:
                    st.error(f"❌ Failed to send email: {error_msg}")
            else:
                st.error("⚠️ Please fill in all required fields")

def show_analytics_reports():
    st.header("📊 Campaign Analytics & Reports")
    
    # Data upload for analysis
    st.subheader("📁 Upload Data for Analysis")
    st.info("💡 Upload your campaign data (CSV/Excel) to generate real insights and reports")
    
    uploaded_file = st.file_uploader(
        "Upload campaign data file",
        type=['csv', 'xlsx'],
        help="Upload CSV or Excel file with campaign performance data"
    )
    
    if uploaded_file:
        try:
            # Read the uploaded file
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)
            
            st.success(f"✅ Data uploaded successfully! Found {len(df)} records with {len(df.columns)} columns.")
            
            # Display basic info about the dataset
            st.subheader("📋 Dataset Overview")
            
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("📊 Total Records", len(df))
            with col2:
                st.metric("📈 Columns", len(df.columns))
            with col3:
                st.metric("💾 File Size", f"{uploaded_file.size / 1024:.1f} KB")
            with col4:
                missing_values = df.isnull().sum().sum()
                st.metric("❓ Missing Values", missing_values)
            
            # Show data preview
            st.subheader("👀 Data Preview")
            st.dataframe(df.head(10), use_container_width=True)
            
            if len(df) > 10:
                st.info(f"Showing first 10 rows of {len(df)} total records")
            
            # Column analysis
            st.subheader("🔍 Column Analysis")
            
            # Detect column types
            numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
            categorical_cols = df.select_dtypes(include=['object']).columns.tolist()
            datetime_cols = df.select_dtypes(include=['datetime']).columns.tolist()
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if numeric_cols:
                    st.write("**📊 Numeric Columns:**")
                    for col in numeric_cols:
                        st.write(f"• {col}")
            
            with col2:
                if categorical_cols:
                    st.write("**📝 Text Columns:**")
                    for col in categorical_cols:
                        st.write(f"• {col}")
            
            with col3:
                if datetime_cols:
                    st.write("**📅 Date Columns:**")
                    for col in datetime_cols:
                        st.write(f"• {col}")
            
            # Generate insights and visualizations
            st.subheader("📈 Automated Insights & Visualizations")
            
            # 1. Summary statistics for numeric columns
            if numeric_cols:
                st.write("**📊 Numeric Column Statistics:**")
                stats_df = df[numeric_cols].describe()
                st.dataframe(stats_df, use_container_width=True)
                
                # Create visualizations for numeric columns
                viz_col1, viz_col2 = st.columns(2)
                
                with viz_col1:
                    if len(numeric_cols) > 0:
                        selected_col = st.selectbox("Select column for histogram:", numeric_cols)
                        fig = px.histogram(df, x=selected_col, title=f"Distribution of {selected_col}")
                        fig.update_layout(template="plotly_dark")
                        st.plotly_chart(fig, use_container_width=True)
                
                with viz_col2:
                    if len(numeric_cols) > 1:
                        col1_select = st.selectbox("X-axis:", numeric_cols, index=0)
                        col2_select = st.selectbox("Y-axis:", numeric_cols, index=1)
                        
                        fig = px.scatter(df, x=col1_select, y=col2_select, 
                                       title=f"{col1_select} vs {col2_select}")
                        fig.update_layout(template="plotly_dark")
                        st.plotly_chart(fig, use_container_width=True)
            
            # 2. Categorical analysis
            if categorical_cols:
                st.write("**📝 Categorical Analysis:**")
                
                cat_col1, cat_col2 = st.columns(2)
                
                with cat_col1:
                    selected_cat = st.selectbox("Select categorical column:", categorical_cols)
                    value_counts = df[selected_cat].value_counts().head(10)
                    
                    fig = px.bar(x=value_counts.index, y=value_counts.values,
                               title=f"Top 10 values in {selected_cat}")
                    fig.update_layout(template="plotly_dark")
                    st.plotly_chart(fig, use_container_width=True)
                
                with cat_col2:
                    # Show unique values count
                    unique_counts = df[categorical_cols].nunique().sort_values(ascending=False)
                    
                    fig = px.bar(x=unique_counts.index, y=unique_counts.values,
                               title="Unique Values per Categorical Column")
                    fig.update_layout(template="plotly_dark")
                    st.plotly_chart(fig, use_container_width=True)
            
            # 3. Missing data analysis
            if missing_values > 0:
                st.write("**❓ Missing Data Analysis:**")
                missing_data = df.isnull().sum()
                missing_data = missing_data[missing_data > 0].sort_values(ascending=False)
                
                fig = px.bar(x=missing_data.index, y=missing_data.values,
                           title="Missing Values by Column")
                fig.update_layout(template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)
            
            # 4. Correlation analysis
            if len(numeric_cols) > 1:
                st.write("**🔗 Correlation Analysis:**")
                corr_matrix = df[numeric_cols].corr()
                
                fig = px.imshow(corr_matrix, 
                              title="Correlation Matrix",
                              color_continuous_scale="RdBu")
                fig.update_layout(template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)
            
            # 5. Data quality report
            st.subheader("🔍 Data Quality Report")
            
            quality_metrics = {
                "Total Records": len(df),
                "Complete Records": len(df.dropna()),
                "Duplicate Records": df.duplicated().sum(),
                "Data Completeness": f"{((len(df) - missing_values) / (len(df) * len(df.columns))) * 100:.1f}%"
            }
            
            quality_col1, quality_col2, quality_col3, quality_col4 = st.columns(4)
            
            with quality_col1:
                st.metric("📊 Total Records", quality_metrics["Total Records"])
            with quality_col2:
                st.metric("✅ Complete Records", quality_metrics["Complete Records"])
            with quality_col3:
                st.metric("🔄 Duplicates", quality_metrics["Duplicate Records"])
            with quality_col4:
                st.metric("📈 Completeness", quality_metrics["Data Completeness"])
            
            # Export options
            st.subheader("📥 Export Analysis")
            
            export_col1, export_col2, export_col3 = st.columns(3)
            
            with export_col1:
                # Summary report
                summary_report = f"""
# Data Analysis Report
Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Dataset Overview
- Total Records: {len(df)}
- Total Columns: {len(df.columns)}
- Missing Values: {missing_values}
- Duplicate Records: {df.duplicated().sum()}
- Data Completeness: {quality_metrics["Data Completeness"]}

## Column Types
- Numeric Columns: {len(numeric_cols)}
- Categorical Columns: {len(categorical_cols)}
- DateTime Columns: {len(datetime_cols)}

## Key Insights
{chr(10).join([f"- {col}: {df[col].describe().to_string()}" for col in numeric_cols[:3]])}
"""
                
                st.download_button(
                    "📄 Download Summary Report",
                    data=summary_report,
                    file_name=f"analysis_report_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                    mime="text/markdown"
                )
            
            with export_col2:
                # Clean dataset
                clean_df = df.dropna()
                csv_clean = clean_df.to_csv(index=False)
                
                st.download_button(
                    "🧹 Download Clean Data",
                    data=csv_clean,
                    file_name=f"clean_data_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv"
                )
            
            with export_col3:
                # Statistics
                if numeric_cols:
                    stats_csv = df[numeric_cols].describe().to_csv()
                    
                    st.download_button(
                        "📊 Download Statistics",
                        data=stats_csv,
                        file_name=f"statistics_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                        mime="text/csv"
                    )
        
        except Exception as e:
            st.error(f"❌ Error processing file: {str(e)}")
            st.info("💡 Please ensure your file is a valid CSV or Excel file with proper formatting.")
    
    else:
        # Show placeholder content when no data is uploaded
        st.info("""
        📁 **No data uploaded yet**
        
        To generate meaningful analytics and reports, please upload your campaign data file (CSV or Excel format).
        
        **Expected data types:**
        - Campaign performance metrics (opens, clicks, conversions)
        - Email engagement data
        - Customer demographics
        - Sales/revenue data
        - Any other campaign-related metrics
        
        Once uploaded, you'll see:
        - 📊 Automated data insights
        - 📈 Interactive visualizations
        - 🔍 Data quality analysis
        - 📋 Summary reports
        - 📥 Export options
        """)
        
        # Show campaign results if available
        if 'campaign_results' in st.session_state:
            st.subheader("📧 Recent Email Campaign Results")
            
            results_df = st.session_state['campaign_results']
            
            # Campaign metrics
            total_sent = len(results_df[results_df['status'] == 'sent'])
            total_failed = len(results_df[results_df['status'] == 'failed'])
            total_invalid = len(results_df[results_df['status'] == 'invalid'])
            success_rate = (total_sent / len(results_df)) * 100 if len(results_df) > 0 else 0
            
            metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
            
            with metric_col1:
                st.metric("📧 Total Emails", len(results_df))
            with metric_col2:
                st.metric("✅ Sent", total_sent)
            with metric_col3:
                st.metric("❌ Failed", total_failed)
            with metric_col4:
                st.metric("📊 Success Rate", f"{success_rate:.1f}%")
            
            # Results breakdown
            status_counts = results_df['status'].value_counts()
            fig = px.pie(values=status_counts.values, names=status_counts.index,
                        title="Email Campaign Results Breakdown")
            fig.update_layout(template="plotly_dark")
            st.plotly_chart(fig, use_container_width=True)
            
            # Detailed results
            with st.expander("📋 View Detailed Results"):
                st.dataframe(results_df, use_container_width=True)

if __name__ == "__main__":
    main()

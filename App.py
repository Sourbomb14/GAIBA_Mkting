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

# Countries and Currencies data
COUNTRIES = [
    "Global", "United States", "Canada", "United Kingdom", "Germany", "France", "Spain", "Italy", 
    "Netherlands", "Belgium", "Sweden", "Norway", "Denmark", "Finland", "Switzerland", "Austria",
    "Australia", "New Zealand", "Japan", "South Korea", "Singapore", "Hong Kong", "India", "China",
    "Brazil", "Mexico", "Argentina", "Chile", "South Africa", "Nigeria", "Kenya", "Egypt",
    "United Arab Emirates", "Saudi Arabia", "Israel", "Turkey", "Russia", "Poland", "Czech Republic"
]

CURRENCIES = [
    "USD - US Dollar", "EUR - Euro", "GBP - British Pound", "CAD - Canadian Dollar", 
    "AUD - Australian Dollar", "JPY - Japanese Yen", "CHF - Swiss Franc", "CNY - Chinese Yuan",
    "INR - Indian Rupee", "BRL - Brazilian Real", "MXN - Mexican Peso", "ZAR - South African Rand",
    "AED - UAE Dirham", "SAR - Saudi Riyal", "SEK - Swedish Krona", "NOK - Norwegian Krone",
    "DKK - Danish Krone", "PLN - Polish Zloty", "CZK - Czech Koruna", "TRY - Turkish Lira"
]

# ================================
# UTILITY CLASSES AND FUNCTIONS
# ================================

def initialize_session_state():
    """Initialize all session state variables"""
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
    def extract_name_from_text(text):
        """Extract potential names from text content"""
        # Common name patterns
        name_patterns = [
            r'\b[A-Z][a-z]+ [A-Z][a-z]+\b',  # FirstName LastName
            r'\b[A-Z]\. [A-Z][a-z]+\b',      # F. LastName
            r'\b[A-Z][a-z]+\b(?=\s*[@\n])',  # FirstName before @ or newline
        ]
        
        names = []
        for pattern in name_patterns:
            matches = re.findall(pattern, text)
            names.extend(matches)
        
        # Filter out common non-name words
        exclude_words = {'Email', 'Name', 'Address', 'Phone', 'Company', 'Dear', 'Hello', 'Hi'}
        names = [name for name in names if name not in exclude_words and len(name.split()) <= 3]
        
        return list(set(names))  # Remove duplicates
    
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
    """Handle email operations with proper functionality"""
    
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
        """Send a single email with proper error handling"""
        if not self.email or not self.password:
            return False, "Email configuration missing"
            
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
                server.send_message(msg)
            
            return True, "Success"
        except Exception as e:
            return False, str(e)
    
    def send_bulk_emails_improved(self, email_list, subject, body_template, personalizer, is_html=True):
        """Improved bulk email sending with proper progress tracking"""
        if not self.email or not self.password:
            st.error("❌ Email configuration missing. Please check your .env file.")
            return pd.DataFrame()
        
        total_emails = len(email_list)
        results = []
        
        # Create progress tracking
        progress_container = st.container()
        with progress_container:
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Real-time metrics
            col1, col2, col3, col4 = st.columns(4)
            sent_metric = col1.empty()
            failed_metric = col2.empty()
            invalid_metric = col3.empty()
            progress_metric = col4.empty()
        
        sent_count = 0
        failed_count = 0
        invalid_count = 0
        
        # Send emails one by one with progress updates
        for index, row in email_list.iterrows():
            # Update progress
            progress = (index + 1) / total_emails
            progress_bar.progress(progress)
            status_text.text(f"Sending email {index + 1} of {total_emails} to {row['email']}...")
            
            if self.validate_email_address(row['email']):
                # Personalize the email
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
                    "error": error_msg if not success else ""
                })
                
                # Small delay between emails to avoid rate limiting
                time.sleep(2)
            else:
                invalid_count += 1
                results.append({
                    "email": row['email'],
                    "name": row.get('name', 'Unknown'),
                    "status": "invalid",
                    "error": "Invalid email format"
                })
            
            # Update metrics in real-time
            sent_metric.metric("✅ Sent", sent_count)
            failed_metric.metric("❌ Failed", failed_count)
            invalid_metric.metric("⚠️ Invalid", invalid_count)
            progress_metric.metric("📊 Progress", f"{progress * 100:.1f}%")
        
        progress_bar.progress(1.0)
        status_text.text("🎉 Email campaign completed!")
        
        return pd.DataFrame(results)

class FileProcessor:
    """Enhanced file processing for contact extraction"""
    
    def __init__(self):
        self.email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        self.personalizer = EmailPersonalizer()
    
    def extract_emails_and_names_from_text(self, text):
        """Extract emails and attempt to find associated names"""
        emails = re.findall(self.email_pattern, text)
        names = self.personalizer.extract_name_from_text(text)
        
        # Try to match names with emails
        contacts = []
        
        for email in emails:
            # First try to extract name from email itself
            auto_name = self.personalizer.extract_name_from_email(email)
            
            # Look for names near this email in the text
            email_index = text.find(email)
            if email_index > 0:
                # Look in the 100 characters before the email
                context = text[max(0, email_index-100):email_index]
                context_names = self.personalizer.extract_name_from_text(context)
                if context_names:
                    auto_name = context_names[0]  # Use the first found name
            
            contacts.append({
                'email': email,
                'name': auto_name
            })
        
        return contacts
    
    def process_csv(self, file):
        """Process CSV file with enhanced name extraction"""
        try:
            df = pd.read_csv(file)
            return self._standardize_dataframe_enhanced(df)
        except Exception as e:
            st.error(f"Error reading CSV file: {e}")
            return None
    
    def process_excel(self, file):
        """Process Excel file with enhanced name extraction"""
        try:
            df = pd.read_excel(file)
            return self._standardize_dataframe_enhanced(df)
        except Exception as e:
            st.error(f"Error reading Excel file: {e}")
            return None
    
    def _standardize_dataframe_enhanced(self, df):
        """Enhanced dataframe standardization with smart name extraction"""
        # Convert all column names to lowercase
        df.columns = df.columns.str.lower()
        
        # Try to find email and name columns
        email_col = None
        name_cols = []
        
        # Look for email column
        for col in df.columns:
            if 'email' in col or 'mail' in col:
                email_col = col
                break
        
        # Look for name columns
        for col in df.columns:
            if any(keyword in col for keyword in ['name', 'first', 'last', 'fname', 'lname', 'full']):
                name_cols.append(col)
        
        if email_col is None:
            # If no email column found, extract from all text
            all_text = ' '.join(df.astype(str).values.flatten())
            contacts = self.extract_emails_and_names_from_text(all_text)
            
            if contacts:
                return pd.DataFrame(contacts)
            else:
                st.error("No email addresses found in the file")
                return None
        
        # Create result dataframe
        result_data = []
        
        for _, row in df.iterrows():
            email = row[email_col]
            if pd.isna(email) or email.strip() == '':
                continue
                
            # Try to construct name from available name columns
            name_parts = []
            for name_col in name_cols:
                if name_col in row and not pd.isna(row[name_col]):
                    name_parts.append(str(row[name_col]).strip())
            
            if name_parts:
                full_name = ' '.join(name_parts)
            else:
                # Fallback to extracting from email
                full_name = self.personalizer.extract_name_from_email(email)
            
            result_data.append({
                'email': email,
                'name': full_name
            })
        
        result_df = pd.DataFrame(result_data)
        
        # Validate emails
        valid_emails = []
        for _, row in result_df.iterrows():
            try:
                validate_email(row['email'])
                valid_emails.append(row)
            except EmailNotValidError:
                continue
        
        if not valid_emails:
            st.error("No valid email addresses found")
            return None
            
        final_df = pd.DataFrame(valid_emails)
        st.success(f"Found {len(final_df)} valid contacts with names!")
        
        return final_df

class CampaignGenerator:
    """Enhanced campaign generator using correct Groq model"""
    
    def __init__(self):
        self.client = None
        if GROQ_API_KEY:
            try:
                self.client = Groq(api_key=GROQ_API_KEY)
            except Exception as e:
                st.error(f"Failed to initialize Groq client: {e}")
    
    def generate_campaign_blueprint(self, campaign_data):
        """Generate comprehensive campaign blueprint using Groq API"""
        if not self.client:
            return self._fallback_campaign_blueprint(campaign_data)
        
        try:
            company_name = campaign_data.get('company_name', 'Your Company')
            campaign_type = campaign_data.get('campaign_type', 'Marketing Campaign')
            target_audience = campaign_data.get('target_audience', 'General audience')
            channels = ', '.join(campaign_data.get('channels', ['Email']))
            location = campaign_data.get('location', 'Global')
            city_state = campaign_data.get('city_state', '')
            budget = campaign_data.get('budget', 'Not specified')
            currency = campaign_data.get('currency', 'USD')
            product_description = campaign_data.get('product_description', 'Product/Service')
            duration = campaign_data.get('duration', 'Not specified')
            customer_segment = campaign_data.get('customer_segment', 'General')
            
            prompt = f"""
            Create a comprehensive and highly detailed marketing campaign blueprint for {company_name}.
            
            Campaign Specifications:
            - Company: {company_name}
            - Campaign Type: {campaign_type}
            - Target Audience: {target_audience}
            - Customer Segment: {customer_segment}
            - Geographic Location: {location}
            - City/State Focus: {city_state}
            - Marketing Channels: {channels}
            - Campaign Duration: {duration}
            - Budget: {budget} {currency}
            - Product/Service: {product_description}
            
            Please create a professional, actionable, and comprehensive marketing campaign blueprint that includes:
            
            1. **EXECUTIVE SUMMARY** - Brief overview and key objectives
            
            2. **CAMPAIGN OBJECTIVES** - Specific, measurable SMART goals aligned with business outcomes
            
            3. **TARGET AUDIENCE ANALYSIS** 
               - Detailed demographic profile
               - Psychographic insights
               - Pain points and motivations
               - Customer journey mapping
               - Buyer personas
            
            4. **MARKET ANALYSIS**
               - Local market conditions for {location} {city_state}
               - Competitive landscape
               - Market opportunities and threats
               - Seasonal considerations
            
            5. **KEY MESSAGING STRATEGY**
               - Primary value proposition
               - Supporting messages for each audience segment
               - Emotional triggers and rational benefits
               - Brand voice and tone guidelines
            
            6. **CHANNEL-SPECIFIC TACTICS**
               - Detailed strategy for each selected channel: {channels}
               - Content formats and frequency
               - Budget allocation per channel
               - Timeline and scheduling
            
            7. **CAMPAIGN TIMELINE & PHASES**
               - Pre-launch preparation (weeks/tasks)
               - Launch phase execution
               - Optimization and scaling phase
               - Post-campaign analysis phase
            
            8. **BUDGET BREAKDOWN**
               - Detailed allocation in {currency}
               - Cost per channel and activity
               - ROI projections
               - Contingency planning
            
            9. **SUCCESS METRICS & KPIs**
               - Primary success metrics
               - Secondary performance indicators
               - Tracking and measurement plan
               - Reporting schedule
            
            10. **RISK MANAGEMENT**
                - Potential challenges and mitigation strategies
                - Backup plans for each major risk
                - Quality assurance checkpoints
            
            11. **IMPLEMENTATION ROADMAP**
                - Step-by-step action plan
                - Resource requirements
                - Team responsibilities
                - Critical milestones
            
            Make this blueprint highly specific to the {customer_segment} segment in {location}, actionable for immediate implementation, and tailored to achieve maximum ROI with the specified budget of {budget} {currency}.
            """
            
            response = self.client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a world-class marketing strategist with 20+ years of experience creating successful campaigns across all industries. Provide detailed, actionable, and highly strategic marketing blueprints that drive real business results."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                model="llama3-8b-8192",  # Using a working Groq model
                temperature=0.7,
                max_tokens=4000
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            st.error(f"Error generating campaign with Groq API: {e}")
            return self._fallback_campaign_blueprint(campaign_data)
    
    def generate_email_content(self, campaign_brief, tone="professional", content_type="html"):
        """Generate email content (HTML or plain text)"""
        if not self.client:
            return self._fallback_email_content(content_type)
        
        try:
            format_instruction = "HTML email template with inline CSS" if content_type == "html" else "plain text email content"
            
            prompt = f"""
            Create a professional {format_instruction} based on this campaign brief:
            
            {campaign_brief}
            
            Requirements:
            - Tone: {tone}
            - Format: {format_instruction}
            - Include personalization placeholders: {{{{first_name}}}}, {{{{name}}}}
            - Include a compelling subject line
            - Clear call-to-action
            - Professional and conversion-focused content
            - Mobile-friendly if HTML
            - Engaging and brand-appropriate
            
            {"Make sure it includes proper HTML structure with inline CSS for email clients." if content_type == "html" else "Keep it clean, professional, and easy to read in plain text format."}
            """
            
            response = self.client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": f"You are an expert email marketing specialist. Create high-converting {format_instruction} that work perfectly across all email clients and drive action."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                model="llama3-8b-8192",
                temperature=0.6,
                max_tokens=3000
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            st.error(f"Error generating email content with Groq API: {e}")
            return self._fallback_email_content(content_type)
    
    def _fallback_campaign_blueprint(self, campaign_data):
        """Enhanced fallback campaign blueprint"""
        company_name = campaign_data.get('company_name', 'Your Company')
        campaign_type = campaign_data.get('campaign_type', 'Marketing Campaign')
        target_audience = campaign_data.get('target_audience', 'General audience')
        channels = ', '.join(campaign_data.get('channels', ['Email']))
        location = campaign_data.get('location', 'Global')
        
        return f"""
# {company_name} - {campaign_type} Campaign Blueprint

## Executive Summary
This comprehensive {campaign_type.lower()} campaign for {company_name} is strategically designed to engage {target_audience} through targeted messaging across {channels} in {location}.

## Campaign Objectives
- **Primary Goal:** Increase brand awareness and market penetration
- **Secondary Goals:** Drive qualified leads, boost conversions, and enhance customer retention
- **Revenue Target:** Achieve positive ROI within first 90 days
- **Engagement Target:** Build lasting relationships with target audience

## Target Audience Analysis
**Primary Audience:** {target_audience}
- **Demographics:** Age, income, education level, and lifestyle characteristics
- **Psychographics:** Values, interests, attitudes, and behavioral patterns
- **Pain Points:** Key challenges our solution addresses
- **Preferred Channels:** {channels} based on audience research
- **Decision Factors:** Price, quality, convenience, and brand trust

## Market Analysis
**Geographic Focus:** {location}
- Local market size and growth potential
- Competitive landscape and positioning opportunities
- Seasonal trends and optimal timing
- Regional preferences and cultural considerations

## Key Messaging Strategy
- **Core Value Proposition:** Clear differentiation and unique benefits
- **Primary Message:** Compelling reason to choose our solution
- **Supporting Points:** Feature benefits and social proof
- **Call-to-Action:** Clear next steps for prospects

## Channel Strategy
**Selected Channels:** {channels}

**Implementation Approach:**
- Integrated multi-channel approach for maximum reach
- Consistent messaging across all touchpoints
- Channel-specific content optimization
- Cross-channel attribution tracking

## Campaign Timeline
**Phase 1: Preparation (Weeks 1-2)**
- Creative development and content creation
- List building and audience segmentation
- Technology setup and testing
- Team training and preparation

**Phase 2: Launch (Weeks 3-4)**
- Campaign deployment across all channels
- Real-time monitoring and optimization
- Customer service preparation
- Initial performance assessment

**Phase 3: Optimization (Weeks 5-6)**
- Performance analysis and insights
- Creative and targeting refinements
- Budget reallocation based on results
- Scaling successful elements

## Success Metrics
- **Awareness:** Brand recall and recognition metrics
- **Engagement:** Click rates, time spent, social interactions  
- **Conversion:** Lead generation and sales conversion rates
- **ROI:** Return on advertising spend and customer acquisition cost

## Implementation Roadmap
1. Finalize campaign creative assets
2. Set up tracking and analytics
3. Prepare audience lists and targeting
4. Launch campaigns across selected channels
5. Monitor performance and optimize daily
6. Analyze results and plan next phase

This blueprint provides the foundation for a successful marketing campaign that will effectively reach your target audience and achieve your business objectives.
"""
    
    def _fallback_email_content(self, content_type):
        """Fallback email content"""
        if content_type == "html":
            return '''<!DOCTYPE html>
<html>
<head>
    <title>Campaign Email</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background-color: #f8f9fa; padding: 30px; text-align: center; }
        .content { padding: 30px; line-height: 1.6; }
        .cta-button { background-color: #007bff; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; display: inline-block; margin: 20px 0; }
        .footer { background-color: #f8f9fa; padding: 20px; text-align: center; font-size: 12px; color: #666; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Hello {{first_name}}!</h1>
    </div>
    <div class="content">
        <p>We're excited to share this special opportunity with you.</p>
        <p>As someone who values quality and innovation, we thought you'd be interested in our latest campaign.</p>
        <a href="#" class="cta-button">Learn More</a>
        <p>Thank you for being part of our community!</p>
    </div>
    <div class="footer">
        <p>Best regards,<br>The Marketing Team</p>
    </div>
</body>
</html>'''
        else:
            return '''Subject: Special Opportunity for {{first_name}}

Hello {{first_name}},

We're excited to share this special opportunity with you.

As someone who values quality and innovation, we thought you'd be interested in our latest campaign.

Here's what makes this opportunity special:
- Personalized experience designed for you
- Exclusive benefits for our community
- Limited-time opportunity to get involved

We believe this will bring real value to your experience with us.

Ready to learn more? Visit our website or reply to this email.

Thank you for being part of our community!

Best regards,
The Marketing Team

---
You received this email because you're a valued member of our community.
Unsubscribe: [link] | Update preferences: [link]'''

# ================================
# STREAMLIT APP CONFIGURATION
# ================================

st.set_page_config(
    page_title="Marketing Campaign Generator",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
initialize_session_state()

# Custom CSS for modern dark theme
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
        padding: 0.5rem 1.5rem;
        font-weight: 600;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(0, 212, 255, 0.3);
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
        
        # Persistent campaign info
        if st.session_state.current_campaign:
            st.markdown("### 🎯 Active Campaign")
            st.info(f"**{st.session_state.current_campaign['company_name']}**")
            st.caption(f"Type: {st.session_state.current_campaign['campaign_type']}")
            st.caption(f"Location: {st.session_state.current_campaign['location']}")
        
        if st.session_state.email_contacts is not None:
            st.markdown("### 📊 Quick Stats")
            st.info(f"📧 Contacts: {len(st.session_state.email_contacts)}")
    
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
            company_name = st.text_input("🏢 Company Name", 
                placeholder="Enter your company name",
                value=st.session_state.current_campaign['company_name'] if st.session_state.current_campaign else "")
            
            campaign_type = st.selectbox("📋 Campaign Type", [
                "Product Launch",
                "Brand Awareness", 
                "Seasonal Campaign",
                "Customer Retention",
                "Lead Generation",
                "Event Promotion",
                "Sales Campaign",
                "Newsletter Campaign"
            ], index=0 if not st.session_state.current_campaign else 
               ["Product Launch", "Brand Awareness", "Seasonal Campaign", "Customer Retention", 
                "Lead Generation", "Event Promotion", "Sales Campaign", "Newsletter Campaign"].index(
                   st.session_state.current_campaign.get('campaign_type', 'Product Launch')))
            
            target_audience = st.text_area("👥 Target Audience", 
                placeholder="Describe your target audience (demographics, interests, etc.)",
                value=st.session_state.current_campaign['target_audience'] if st.session_state.current_campaign else "")
            
            duration = st.text_input("📅 Campaign Duration", 
                placeholder="e.g., 4 weeks, 2 months",
                value=st.session_state.current_campaign['duration'] if st.session_state.current_campaign else "")
        
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
            ], default=st.session_state.current_campaign['channels'] if st.session_state.current_campaign else [])
            
            location = st.selectbox("🌍 Country", COUNTRIES,
                index=COUNTRIES.index(st.session_state.current_campaign['location']) if st.session_state.current_campaign and st.session_state.current_campaign['location'] in COUNTRIES else 0)
            
            city_state = st.text_input("🏙️ City/State (Optional)", 
                placeholder="e.g., New York, NY or London",
                value=st.session_state.current_campaign.get('city_state', '') if st.session_state.current_campaign else "")
            
            customer_segment = st.selectbox("💼 Customer Segment",
                ["Mass Market", "Premium", "Niche", "Enterprise", "SMB"],
                index=0 if not st.session_state.current_campaign else 
                ["Mass Market", "Premium", "Niche", "Enterprise", "SMB"].index(
                    st.session_state.current_campaign.get('customer_segment', 'Mass Market')))
        
        # Budget and Currency
        budget_col1, budget_col2 = st.columns(2)
        with budget_col1:
            budget = st.text_input("💰 Budget Amount", 
                placeholder="e.g., 10000",
                value=st.session_state.current_campaign.get('budget', '') if st.session_state.current_campaign else "")
        with budget_col2:
            currency = st.selectbox("💱 Currency", CURRENCIES,
                index=0 if not st.session_state.current_campaign else 
                (CURRENCIES.index(st.session_state.current_campaign['currency']) 
                 if st.session_state.current_campaign.get('currency') in CURRENCIES else 0))
        
        product_description = st.text_area("📦 Product/Service Description",
            placeholder="Describe what you're promoting in this campaign...",
            value=st.session_state.current_campaign.get('product_description', '') if st.session_state.current_campaign else "")
        
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
            'city_state': city_state,
            'customer_segment': customer_segment,
            'budget': budget,
            'currency': currency,
            'product_description': product_description
        }
        
        with st.spinner("🤖 AI is analyzing your requirements and generating a comprehensive campaign strategy..."):
            generator = CampaignGenerator()
            blueprint = generator.generate_campaign_blueprint(campaign_data)
            
            # Store in session state
            st.session_state.current_campaign = campaign_data
            st.session_state.campaign_blueprint = blueprint
            
            st.success("✨ AI-powered campaign blueprint generated successfully!")
            st.balloons()
    
    # Display existing blueprint if available
    if st.session_state.campaign_blueprint:
        st.markdown("## 📋 Your AI-Generated Campaign Blueprint")
        st.markdown(st.session_state.campaign_blueprint)
        
        # Action buttons
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("📧 Create Email Campaign", use_container_width=True):
                st.switch_page("pages/email_marketing.py") if hasattr(st, 'switch_page') else st.rerun()
        with col2:
            if st.button("📊 View Analytics", use_container_width=True):
                st.switch_page("pages/analytics.py") if hasattr(st, 'switch_page') else st.rerun()
        with col3:
            if st.session_state.current_campaign:
                st.download_button("📄 Download Blueprint", 
                    data=st.session_state.campaign_blueprint, 
                    file_name=f"{st.session_state.current_campaign['company_name']}_campaign_blueprint.md",
                    mime="text/markdown",
                    use_container_width=True)
    
    elif submitted:
        st.error("⚠️ Please fill in at least Company Name and Campaign Type")

def show_email_marketing():
    st.header("📧 AI Email Marketing Center")
    
    email_handler = EmailHandler()
    personalizer = EmailPersonalizer()
    file_processor = FileProcessor()
    
    # Show active campaign info
    if st.session_state.current_campaign:
        st.success(f"🎯 Active Campaign: **{st.session_state.current_campaign['company_name']}** - {st.session_state.current_campaign['campaign_type']}")
    else:
        st.info("💡 Create a campaign first in the Campaign Dashboard for AI-generated content")
    
    # Email Content Generation
    st.subheader("🎨 AI Email Content Generator")
    
    content_col1, content_col2 = st.columns(2)
    
    with content_col1:
        email_type = st.selectbox("📧 Email Type", [
            "Welcome Email",
            "Product Announcement", 
            "Promotional Offer",
            "Newsletter",
            "Follow-up Email",
            "Event Invitation",
            "Customer Survey",
            "Abandoned Cart",
            "Thank You Email"
        ])
        
        tone = st.selectbox("🎭 Tone", ["Professional", "Friendly", "Casual", "Urgent", "Formal", "Enthusiastic"])
        
        content_format = st.radio("📝 Email Format", ["HTML Template", "Plain Text Content"])
    
    with content_col2:
        if st.button("🚀 Generate AI Email Content", type="primary", use_container_width=True):
            if st.session_state.campaign_blueprint:
                generator = CampaignGenerator()
                
                with st.spinner("🤖 AI is crafting your personalized email content..."):
                    content_type = "html" if content_format == "HTML Template" else "plain"
                    content = generator.generate_email_content(
                        st.session_state.campaign_blueprint, 
                        tone.lower(), 
                        content_type
                    )
                    
                    if content_type == "html":
                        st.session_state.email_template = content
                    else:
                        st.session_state.plain_text_template = content
                    
                    st.success(f"✨ {content_format} generated successfully!")
            else:
                st.warning("⚠️ Please create a campaign first to generate AI content")
    
    # Template Editor and Preview
    if st.session_state.email_template or st.session_state.plain_text_template:
        st.markdown("---")
        st.subheader("📝 Email Content Editor")
        
        # Choose which template to edit
        if st.session_state.email_template and st.session_state.plain_text_template:
            edit_choice = st.radio("Edit:", ["HTML Template", "Plain Text Content"])
            template_to_edit = st.session_state.email_template if edit_choice == "HTML Template" else st.session_state.plain_text_template
        elif st.session_state.email_template:
            edit_choice = "HTML Template"
            template_to_edit = st.session_state.email_template
        else:
            edit_choice = "Plain Text Content"
            template_to_edit = st.session_state.plain_text_template
        
        # Editor
        edited_content = st.text_area(
            f"Edit your {edit_choice.lower()}:",
            value=template_to_edit,
            height=400,
            help="Use {first_name}, {name}, and {email} for personalization"
        )
        
        # Update session state
        if edit_choice == "HTML Template":
            st.session_state.email_template = edited_content
        else:
            st.session_state.plain_text_template = edited_content
        
        # Preview for HTML
        if edit_choice == "HTML Template":
            if st.button("👀 Preview HTML Template"):
                preview_name = "John Smith"
                preview_email = "john.smith@example.com"
                
                preview_content = personalizer.personalize_template(
                    edited_content, 
                    preview_name, 
                    preview_email
                )
                
                st.markdown("### 📧 Email Preview")
                st.components.v1.html(preview_content, height=600, scrolling=True)
    
    st.markdown("---")
    
    # Enhanced Contact Import
    st.subheader("👥 Import Email Contacts with Smart Name Extraction")
    
    import_tab1, import_tab2 = st.tabs(["📁 File Upload", "✍️ Manual Entry"])
    
    with import_tab1:
        st.write("**Upload files with automatic name extraction from emails and content**")
        uploaded_file = st.file_uploader(
            "Upload contact file",
            type=['csv', 'xlsx', 'txt'],
            help="Upload CSV, Excel, or text file. Names will be automatically extracted!"
        )
        
        if uploaded_file:
            file_extension = uploaded_file.name.split('.')[-1].lower()
            
            with st.spinner("🔍 Processing file and extracting names..."):
                if file_extension == 'csv':
                    df = file_processor.process_csv(uploaded_file)
                elif file_extension in ['xlsx', 'xls']:
                    df = file_processor.process_excel(uploaded_file)
                elif file_extension == 'txt':
                    # Handle text files
                    text_content = str(uploaded_file.read(), "utf-8")
                    contacts = file_processor.extract_emails_and_names_from_text(text_content)
                    df = pd.DataFrame(contacts) if contacts else None
                
                if df is not None and not df.empty:
                    st.session_state.email_contacts = df
                    st.success(f"✅ Loaded {len(df)} contacts with smart name extraction!")
                    
                    # Show editable preview
                    edited_contacts = st.data_editor(
                        df,
                        column_config={
                            "email": st.column_config.TextColumn("📧 Email"),
                            "name": st.column_config.TextColumn("👤 Name (Auto-extracted)")
                        },
                        num_rows="dynamic",
                        use_container_width=True,
                        key="contact_editor"
                    )
                    
                    if st.button("💾 Save Edited Contacts"):
                        st.session_state.email_contacts = edited_contacts
                        st.success("Contacts updated!")
    
    with import_tab2:
        st.write("**Manual entry with automatic name detection**")
        manual_input = st.text_area(
            "Paste emails and names (any format):",
            placeholder="""john.smith@company.com
Jane Doe <jane@business.org>
Bob Wilson - bob.wilson@startup.co
sarah@company.com (Sarah Johnson)

Or just paste a list of emails - names will be auto-extracted!""",
            height=200
        )
        
        if st.button("🔍 Process and Extract Names") and manual_input:
            with st.spinner("Extracting emails and names..."):
                contacts = file_processor.extract_emails_and_names_from_text(manual_input)
                
                if contacts:
                    df = pd.DataFrame(contacts)
                    st.session_state.email_contacts = df
                    st.success(f"✅ Found {len(contacts)} contacts with names!")
                    
                    st.dataframe(df, use_container_width=True)
                else:
                    st.error("No valid email addresses found")
    
    # Email Campaign Launch
    if st.session_state.email_contacts is not None and (st.session_state.email_template or st.session_state.plain_text_template):
        st.markdown("---")
        st.subheader("🚀 Launch Personalized Email Campaign")
        
        df = st.session_state.email_contacts
        
        # Campaign metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("👥 Total Contacts", len(df))
        with col2:
            unique_names = df['name'].nunique()
            st.metric("🏷️ Unique Names", unique_names)
        with col3:
            domains = df['email'].str.split('@').str[1].nunique()
            st.metric("🏢 Email Domains", domains)
        with col4:
            template_status = "✅ Ready" if st.session_state.email_template or st.session_state.plain_text_template else "❌ Missing"
            st.metric("📧 Template", template_status)
        
        # Campaign configuration
        config_col1, config_col2 = st.columns(2)
        
        with config_col1:
            subject = st.text_input("📧 Email Subject", 
                value="Important message for {first_name}",
                help="Use {name} and {first_name} for personalization")
            
            # Choose template type
            if st.session_state.email_template and st.session_state.plain_text_template:
                email_format = st.radio("📝 Send Format", ["HTML Email", "Plain Text Email"])
            elif st.session_state.email_template:
                email_format = "HTML Email"
                st.info("HTML template ready")
            else:
                email_format = "Plain Text Email"
                st.info("Plain text template ready")
        
        with config_col2:
            test_email = st.text_input("🧪 Test Email", 
                placeholder="your-email@example.com")
            
            if st.button("🧪 Send Test Email") and test_email:
                template_content = st.session_state.email_template if email_format == "HTML Email" else st.session_state.plain_text_template
                is_html = email_format == "HTML Email"
                
                test_content = personalizer.personalize_template(template_content, "Test User", test_email)
                test_subject = personalizer.personalize_template(subject, "Test User", test_email)
                
                success, error_msg = email_handler.send_single_email(
                    test_email, 
                    test_subject, 
                    test_content, 
                    is_html=is_html
                )
                
                if success:
                    st.success("✅ Test email sent successfully!")
                else:
                    st.error(f"❌ Failed to send test email: {error_msg}")
        
        # Launch campaign
        st.markdown("### 🎯 Campaign Launch")
        
        if st.button("🚀 LAUNCH PERSONALIZED EMAIL CAMPAIGN", type="primary", use_container_width=True):
            if not GMAIL_USER or not GMAIL_APP_PASSWORD:
                st.error("❌ Email configuration missing. Please check your .env file.")
                return
            
            template_content = st.session_state.email_template if email_format == "HTML Email" else st.session_state.plain_text_template
            is_html = email_format == "HTML Email"
            
            st.warning(f"⚠️ You are about to send {len(df)} personalized {email_format.lower()}s. This cannot be undone!")
            
            if st.button("✅ CONFIRM LAUNCH"):
                st.info("🚀 Launching personalized email campaign...")
                
                results = email_handler.send_bulk_emails_improved(
                    df, subject, template_content, personalizer, is_html=is_html
                )
                
                if not results.empty:
                    # Show results
                    success_count = len(results[results['status'] == 'sent'])
                    failed_count = len(results[results['status'] == 'failed'])
                    invalid_count = len(results[results['status'] == 'invalid'])
                    
                    st.success("🎉 Personalized email campaign completed!")
                    
                    result_col1, result_col2, result_col3, result_col4 = st.columns(4)
                    
                    with result_col1:
                        st.metric("✅ Sent", success_count)
                    with result_col2:
                        st.metric("❌ Failed", failed_count)
                    with result_col3:
                        st.metric("⚠️ Invalid", invalid_count)
                    with result_col4:
                        success_rate = (success_count / len(results)) * 100
                        st.metric("📊 Success Rate", f"{success_rate:.1f}%")
                    
                    # Store results
                    st.session_state.campaign_results = results
                    
                    # Download results
                    csv = results.to_csv(index=False)
                    st.download_button(
                        "📥 Download Campaign Results",
                        data=csv,
                        file_name=f"campaign_results_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                        mime="text/csv"
                    )
                    
                    # Show detailed results
                    with st.expander("📋 View Detailed Results"):
                        st.dataframe(results, use_container_width=True)
    
    # Quick single email with personalization
    st.markdown("---")
    st.subheader("📧 Quick Personalized Email")
    
    with st.form("single_email_form"):
        single_col1, single_col2 = st.columns(2)
        
        with single_col1:
            recipient = st.text_input("📧 Recipient Email")
            recipient_name = st.text_input("👤 Name (auto-detected if empty)")
        
        with single_col2:
            single_subject = st.text_input("📝 Subject (use {name} for personalization)")
            use_template = st.checkbox("Use Generated Template", 
                value=bool(st.session_state.email_template or st.session_state.plain_text_template))
        
        if use_template and (st.session_state.email_template or st.session_state.plain_text_template):
            if st.session_state.email_template and st.session_state.plain_text_template:
                template_choice = st.radio("Template Type", ["HTML Template", "Plain Text Template"])
                template_content = st.session_state.email_template if template_choice == "HTML Template" else st.session_state.plain_text_template
            elif st.session_state.email_template:
                template_content = st.session_state.email_template
                template_choice = "HTML Template"
            else:
                template_content = st.session_state.plain_text_template
                template_choice = "Plain Text Template"
            
            body = st.text_area("📧 Email Content", value=template_content, height=300)
            is_html_email = template_choice == "HTML Template"
        else:
            body = st.text_area("📧 Email Content", height=300)
            is_html_email = st.checkbox("Send as HTML")
        
        if st.form_submit_button("📧 Send Personalized Email", use_container_width=True):
            if recipient and single_subject and body:
                # Auto-detect name if not provided
                final_name = recipient_name if recipient_name else personalizer.extract_name_from_email(recipient)
                
                # Personalize content
                final_body = personalizer.personalize_template(body, final_name, recipient)
                final_subject = personalizer.personalize_template(single_subject, final_name, recipient)
                
                success, error_msg = email_handler.send_single_email(
                    recipient, final_subject, final_body, is_html=is_html_email
                )
                
                if success:
                    st.success(f"✅ Personalized email sent to **{final_name}** ({recipient})!")
                else:
                    st.error(f"❌ Failed to send email: {error_msg}")
            else:
                st.error("⚠️ Please fill in all required fields")

def show_analytics_reports():
    st.header("📊 Campaign Analytics & Reports")
    
    # Data upload for analysis
    st.subheader("📁 Upload Campaign Data for Analysis")
    st.info("💡 Upload your campaign performance data (CSV/Excel) to generate real insights and reports")
    
    uploaded_file = st.file_uploader(
        "Upload campaign data file",
        type=['csv', 'xlsx'],
        help="Upload CSV or Excel file with campaign performance data (opens, clicks, conversions, etc.)"
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
            st.subheader("📈 Automated Campaign Insights")
            
            # 1. Summary statistics for numeric columns
            if numeric_cols:
                st.write("**📊 Performance Metrics Summary:**")
                stats_df = df[numeric_cols].describe()
                st.dataframe(stats_df, use_container_width=True)
                
                # Create visualizations for numeric columns
                viz_col1, viz_col2 = st.columns(2)
                
                with viz_col1:
                    if len(numeric_cols) > 0:
                        selected_col = st.selectbox("Select metric for distribution:", numeric_cols)
                        fig = px.histogram(df, x=selected_col, 
                                         title=f"Distribution of {selected_col}",
                                         nbins=20)
                        fig.update_layout(template="plotly_dark")
                        st.plotly_chart(fig, use_container_width=True)
                
                with viz_col2:
                    if len(numeric_cols) > 1:
                        col1_select = st.selectbox("X-axis metric:", numeric_cols, index=0)
                        col2_select = st.selectbox("Y-axis metric:", numeric_cols, index=1)
                        
                        fig = px.scatter(df, x=col1_select, y=col2_select, 
                                       title=f"{col1_select} vs {col2_select}")
                        fig.update_layout(template="plotly_dark")
                        st.plotly_chart(fig, use_container_width=True)
            
            # 2. Campaign performance trends
            if datetime_cols and numeric_cols:
                st.write("**📈 Campaign Performance Over Time:**")
                date_col = st.selectbox("Select date column:", datetime_cols)
                metric_col = st.selectbox("Select performance metric:", numeric_cols)
                
                # Ensure date column is datetime
                df[date_col] = pd.to_datetime(df[date_col])
                
                fig = px.line(df.sort_values(date_col), x=date_col, y=metric_col,
                            title=f"{metric_col} Over Time")
                fig.update_layout(template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)
            
            # 3. Categorical analysis
            if categorical_cols:
                st.write("**📝 Campaign Segmentation Analysis:**")
                
                cat_col1, cat_col2 = st.columns(2)
                
                with cat_col1:
                    selected_cat = st.selectbox("Select category:", categorical_cols)
                    value_counts = df[selected_cat].value_counts().head(10)
                    
                    fig = px.bar(x=value_counts.index, y=value_counts.values,
                               title=f"Top 10 values in {selected_cat}")
                    fig.update_layout(template="plotly_dark")
                    st.plotly_chart(fig, use_container_width=True)
                
                with cat_col2:
                    if numeric_cols and categorical_cols:
                        metric_for_segment = st.selectbox("Performance metric for analysis:", numeric_cols)
                        category_for_segment = st.selectbox("Segment by:", categorical_cols)
                        
                        fig = px.box(df, x=category_for_segment, y=metric_for_segment,
                                   title=f"{metric_for_segment} by {category_for_segment}")
                        fig.update_layout(template="plotly_dark")
                        st.plotly_chart(fig, use_container_width=True)
            
            # 4. Correlation analysis
            if len(numeric_cols) > 1:
                st.write("**🔗 Performance Metrics Correlation:**")
                corr_matrix = df[numeric_cols].corr()
                
                fig = px.imshow(corr_matrix, 
                              title="Correlation Matrix of Performance Metrics",
                              color_continuous_scale="RdBu",
                              aspect="auto")
                fig.update_layout(template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)
            
            # 5. Data quality report
            st.subheader("🔍 Data Quality Assessment")
            
            quality_col1, quality_col2, quality_col3, quality_col4 = st.columns(4)
            
            with quality_col1:
                st.metric("📊 Total Records", len(df))
            with quality_col2:
                complete_records = len(df.dropna())
                st.metric("✅ Complete Records", complete_records)
            with quality_col3:
                duplicates = df.duplicated().sum()
                st.metric("🔄 Duplicate Records", duplicates)
            with quality_col4:
                completeness = ((len(df) * len(df.columns) - missing_values) / (len(df) * len(df.columns))) * 100
                st.metric("📈 Data Completeness", f"{completeness:.1f}%")
            
            # Export options
            st.subheader("📥 Export Analysis Results")
            
            export_col1, export_col2, export_col3 = st.columns(3)
            
            with export_col1:
                # Summary report
                summary_report = f"""
# Campaign Data Analysis Report
Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Dataset Overview
- **Total Records:** {len(df)}
- **Total Columns:** {len(df.columns)}
- **Missing Values:** {missing_values}
- **Duplicate Records:** {duplicates}
- **Data Completeness:** {completeness:.1f}%

## Column Types
- **Numeric Columns:** {len(numeric_cols)}
- **Categorical Columns:** {len(categorical_cols)}
- **DateTime Columns:** {len(datetime_cols)}

## Key Performance Insights
{chr(10).join([f"- **{col}:** Mean: {df[col].mean():.2f}, Std: {df[col].std():.2f}" for col in numeric_cols[:5]])}

## Data Quality
- **Completeness:** {completeness:.1f}%
- **Unique Records:** {len(df) - duplicates}
- **Data Integrity:** {'Good' if completeness > 90 else 'Needs Attention'}
"""
                
                st.download_button(
                    "📄 Download Analysis Report",
                    data=summary_report,
                    file_name=f"campaign_analysis_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                    mime="text/markdown"
                )
            
            with export_col2:
                # Clean dataset
                clean_df = df.dropna()
                csv_clean = clean_df.to_csv(index=False)
                
                st.download_button(
                    "🧹 Download Clean Dataset",
                    data=csv_clean,
                    file_name=f"clean_campaign_data_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv"
                )
            
            with export_col3:
                # Statistics summary
                if numeric_cols:
                    stats_csv = df[numeric_cols].describe().to_csv()
                    
                    st.download_button(
                        "📊 Download Statistics Summary",
                        data=stats_csv,
                        file_name=f"campaign_stats_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                        mime="text/csv"
                    )
        
        except Exception as e:
            st.error(f"❌ Error processing file: {str(e)}")
            st.info("💡 Please ensure your file is a valid CSV or Excel file with campaign performance data.")
    
    else:
        # Show campaign results if available
        if st.session_state.campaign_results is not None:
            st.subheader("📧 Recent Email Campaign Results")
            
            results_df = st.session_state.campaign_results
            
            # Campaign metrics
            total_sent = len(results_df[results_df['status'] == 'sent'])
            total_failed = len(results_df[results_df['status'] == 'failed'])
            total_invalid = len(results_df[results_df['status'] == 'invalid'])
            success_rate = (total_sent / len(results_df)) * 100 if len(results_df) > 0 else 0
            
            metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
            
            with metric_col1:
                st.metric("📧 Total Emails", len(results_df))
            with metric_col2:
                st.metric("✅ Successfully Sent", total_sent)
            with metric_col3:
                st.metric("❌ Failed", total_failed)
            with metric_col4:
                st.metric("📊 Success Rate", f"{success_rate:.1f}%")
            
            # Results visualization
            if len(results_df) > 0:
                status_counts = results_df['status'].value_counts()
                fig = px.pie(values=status_counts.values, names=status_counts.index,
                            title="Email Campaign Results Distribution",
                            color_discrete_map={
                                'sent': '#28a745',
                                'failed': '#dc3545', 
                                'invalid': '#ffc107'
                            })
                fig.update_layout(template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)
                
                # Show detailed results
                with st.expander("📋 View Detailed Campaign Results"):
                    st.dataframe(results_df, use_container_width=True)
        else:
            st.info("""
            📊 **No data available for analysis**
            
            To view campaign analytics:
            1. **Upload campaign performance data** using the file uploader above, or
            2. **Run an email campaign** in the Email Marketing section to see results here
            
            **Expected data formats:**
            - Email campaign metrics (opens, clicks, conversions, bounces)
            - Customer engagement data  
            - Sales and revenue data
            - A/B testing results
            - Social media performance metrics
            """)

if __name__ == "__main__":
    main()

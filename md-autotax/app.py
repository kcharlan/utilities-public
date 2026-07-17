import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path
import os
import tempfile

from md_autotax_core import (
    ConfigError,
    generate_qif_content,
    load_config,
    load_tax_table,
    write_qif,
)

# --- Updated CSS matching the Whisper app style ---
st.markdown("""
<style>
    .main-header {
        text-align: center;
        padding: 1rem 0 2rem 0;
        background: linear-gradient(90deg, #10b981 0%, #059669 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        font-size: 2.5rem;
        font-weight: 700;
        margin-bottom: 0;
    }
    
    .subtitle {
        text-align: center;
        color: #6b7280;
        font-size: 1.1rem;
        margin-bottom: 2rem;
    }
    
    .section-header {
        color: #374151;
        font-weight: 600;
        font-size: 1.3rem;
        margin: 2rem 0 1rem 0;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid #e5e7eb;
    }
    
    /* Style the file uploader */
    .stFileUploader {
        background: linear-gradient(135deg, #10b98110 0%, #05966910 100%) !important;
        border-radius: 12px !important;
        padding: 1.5rem !important;
        margin: 1rem 0 !important;
        border: 2px dashed #10b981 !important;
        transition: all 0.3s ease;
    }
    
    .stFileUploader:hover {
        border-color: #059669 !important;
        background: linear-gradient(135deg, #10b98120 0%, #05966920 100%) !important;
    }
    
    .stFileUploader > div {
        border: none !important;
        background: transparent !important;
    }
    
    /* Form styling */
    .stSelectbox > div > div {
        background-color: var(--background-color, #f9fafb) !important;
        border-radius: 8px;
    }
    
    .stSelectbox > div > div > div {
        color: var(--text-color, #1f2937) !important;
    }
    
    .stTextInput > div > div > input {
        background-color: var(--background-color, #f9fafb) !important;
        border-radius: 8px;
        border: 1px solid #d1d5db;
        color: var(--text-color, #1f2937) !important;
    }
    
    .stDateInput > div > div > input {
        background-color: var(--background-color, #f9fafb) !important;
        border-radius: 8px;
        border: 1px solid #d1d5db;
        color: var(--text-color, #1f2937) !important;
    }
    
    .stButton > button {
        background: linear-gradient(90deg, #10b981 0%, #059669 100%) !important;
        color: white !important;
        border-radius: 8px;
        border: none;
        padding: 0.6rem 2rem;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(16, 185, 129, 0.4);
    }
    
    .stButton > button:disabled {
        background: #9ca3af !important;
        transform: none !important;
        box-shadow: none !important;
    }
    
    /* Tax table styling */
    .tax-card {
        background: var(--secondary-background-color, white);
        border-radius: 12px;
        padding: 1rem;
        margin: 0.5rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        border-left: 4px solid #10b981;
        cursor: pointer;
        transition: all 0.3s ease;
    }
    
    .tax-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(16, 185, 129, 0.2);
    }
    
    .tax-card.selected {
        border-left-color: #059669;
        background: linear-gradient(135deg, #10b98110 0%, #05966910 100%);
    }
    
    .tax-amount {
        font-size: 1.5rem;
        font-weight: 700;
        color: #059669;
        margin-bottom: 0.5rem;
    }
    
    .tax-details {
        font-size: 0.9rem;
        color: #6b7280;
        display: flex;
        justify-content: space-between;
    }
    
    .stAlert {
        border-radius: 8px;
    }
    
    /* Dark mode specific overrides */
    @media (prefers-color-scheme: dark) {
        .stSelectbox > div > div {
            background-color: #374151 !important;
        }
        
        .stSelectbox > div > div > div {
            color: #f9fafb !important;
        }
        
        .stTextInput > div > div > input {
            background-color: #374151 !important;
            color: #f9fafb !important;
            border-color: #4b5563;
        }
        
        .stDateInput > div > div > input {
            background-color: #374151 !important;
            color: #f9fafb !important;
            border-color: #4b5563;
        }
        
        .stFileUploader {
            background: linear-gradient(135deg, #10b98115 0%, #05966915 100%) !important;
            border-color: #10b981 !important;
        }
        
        .stFileUploader:hover {
            border-color: #059669 !important;
            background: linear-gradient(135deg, #10b98125 0%, #05966925 100%) !important;
        }
        
        .tax-card {
            background: #1f2937;
        }
        
        .tax-card.selected {
            background: linear-gradient(135deg, #10b98115 0%, #05966915 100%);
        }
        
        .section-header {
            color: #f9fafb;
            border-bottom-color: #4b5563;
        }
        
        .subtitle {
            color: #9ca3af;
        }
    }
</style>
""", unsafe_allow_html=True)

# --- Streamlit UI ---

st.set_page_config(
    page_title="Tax QIF Generator", 
    layout="wide",
    page_icon="💰"
)

# Initialize session state
if 'selected_income' not in st.session_state:
    st.session_state.selected_income = None
if 'output_dir' not in st.session_state:
    st.session_state.output_dir = os.getcwd()

# Header
st.markdown('<h1 class="main-header">💰 Tax QIF Generator</h1>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">Generate QIF files for estimated tax payments with ease</p>', unsafe_allow_html=True)

try:
    private_config = load_config()
except ConfigError as exc:
    st.error(f"Private configuration error: {exc}")
    st.stop()

# Configuration Section
st.markdown('<h3 class="section-header">📋 Tax Table Configuration</h3>', unsafe_allow_html=True)

# The operational tax table is private and configured outside the repository.
default_tax_table = private_config["tax_table"]

col1, col2 = st.columns([2, 1])

with col1:
    tax_table_path = st.text_input(
        "Tax Table CSV Path",
        value=default_tax_table,
        help="📁 Path to your tax table CSV file"
    )

with col2:
    st.write("")  # Spacing
    st.write("")  # More spacing for alignment
    uploaded_tax_file = st.file_uploader(
        "Or upload CSV",
        type=["csv"],
        help="📎 Upload your tax table CSV file"
    )

# Load tax table
tax_df = None
error_msg = None

if uploaded_tax_file:
    # Save uploaded file to temp location and use it
    with tempfile.NamedTemporaryFile(delete=False, suffix='.csv') as tmp_file:
        tmp_file.write(uploaded_tax_file.getbuffer())
        tax_df, error_msg = load_tax_table(tmp_file.name)
    if error_msg:
        st.error(f"❌ Error loading uploaded tax table: {error_msg}")
elif os.path.exists(tax_table_path):
    tax_df, error_msg = load_tax_table(tax_table_path)
    if error_msg:
        st.error(f"❌ Error loading tax table: {error_msg}")
else:
    st.warning(f"⚠️ Tax table not found at: {tax_table_path}")

# Tax Selection Section
if tax_df is not None:
    st.markdown('<h3 class="section-header">💵 Select Income Level</h3>', unsafe_allow_html=True)
    
    # Create formatted options for selectbox
    options = []
    for idx, row in tax_df.iterrows():
        income = row['MonthlyIncome']
        fed_tax = row['FederalTax']
        state_tax = row['StateTax']
        total_tax = fed_tax + state_tax
        option_text = f"${income:,.0f}/month → Federal: ${fed_tax:,.2f} | State: ${state_tax:,.2f} | Total: ${total_tax:,.2f}"
        options.append((option_text, income))
    
    # Selectbox for income selection
    selected_option = st.selectbox(
        "Choose your monthly income level:",
        options=[opt[0] for opt in options],
        index=None,
        placeholder="Select an income level...",
        help="💡 Choose the income level that matches your monthly gross income"
    )
    
    # Update session state when selection changes
    if selected_option:
        # Find the corresponding income value
        for opt_text, income_val in options:
            if opt_text == selected_option:
                st.session_state.selected_income = income_val
                break
        
        # Show confirmation with details
        selected_row = tax_df[tax_df['MonthlyIncome'] == st.session_state.selected_income].iloc[0]
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Monthly Income", f"${st.session_state.selected_income:,.0f}")
        with col2:
            st.metric("Federal Tax", f"${selected_row['FederalTax']:,.2f}")
        with col3:
            st.metric("State Tax", f"${selected_row['StateTax']:,.2f}")
        with col4:
            st.metric("Total Tax", f"${selected_row['FederalTax'] + selected_row['StateTax']:,.2f}")
    else:
        st.session_state.selected_income = None

# Date and Output Configuration
st.markdown('<h3 class="section-header">📅 Transaction Details</h3>', unsafe_allow_html=True)

col1, col2 = st.columns([1, 1])

with col1:
    target_date = st.date_input(
        "Transaction Date",
        value=datetime.now().date(),
        help="📅 Date for the tax payment transaction"
    )

with col2:
    output_dir = st.text_input(
        "Output Directory",
        value=st.session_state.output_dir,
        help="📂 Directory where the QIF file will be saved"
    )
    # Update session state
    st.session_state.output_dir = output_dir

# Simple directory shortcuts
st.write("**Quick Directory Selection:**")
dir_cols = st.columns(4)
common_dirs = {
    "Current": os.getcwd(),
    "Desktop": os.path.join(os.path.expanduser("~"), "Desktop"),
    "Documents": os.path.join(os.path.expanduser("~"), "Documents"),
    "Downloads": os.path.join(os.path.expanduser("~"), "Downloads")
}

for idx, (name, path) in enumerate(common_dirs.items()):
    col = dir_cols[idx]
    with col:
        if os.path.exists(path):
            if st.button(f"📁 {name}", key=f"dir_{name.lower()}"):
                st.session_state.output_dir = path
                st.rerun()

# Generation Section
st.markdown('<h3 class="section-header">🚀 Generate QIF</h3>', unsafe_allow_html=True)

# Check if we can generate
can_generate = (
    tax_df is not None and 
    st.session_state.get('selected_income') is not None and 
    os.path.exists(st.session_state.output_dir)
)

if not can_generate:
    missing_items = []
    if tax_df is None:
        missing_items.append("Tax table")
    if st.session_state.get('selected_income') is None:
        missing_items.append("Income selection")
    if not os.path.exists(st.session_state.output_dir):
        missing_items.append("Valid output directory")
    
    st.info(f"📝 Missing: {', '.join(missing_items)}")

generate_btn = st.button(
    "💾 Generate QIF File",
    disabled=not can_generate,
    help="Click to generate your QIF file for estimated taxes"
)

# Generation Logic
if generate_btn and can_generate:
    try:
        selected_row = tax_df[tax_df['MonthlyIncome'] == st.session_state.selected_income].iloc[0]
        
        # Generate QIF content
        qif_content = generate_qif_content(
            datetime.combine(target_date, datetime.min.time()),
            selected_row['FederalTax'],
            selected_row['StateTax'],
            private_config,
        )
        
        # Create filename
        filename = f"tax_entries_{target_date.strftime('%Y-%m-%d')}.qif"
        filepath = os.path.join(st.session_state.output_dir, filename)
        
        # Write with private file permissions and atomic replacement.
        write_qif(Path(filepath), qif_content)
        
        st.success(f"✅ QIF file generated successfully!")
        st.info(f"📁 Saved to: `{filepath}`")
        
        # Show file preview
        with st.expander("👀 Preview Generated QIF"):
            st.code(qif_content, language="text")
        
        # Offer download
        st.download_button(
            label="⬇️ Download QIF File",
            data=qif_content,
            file_name=filename,
            mime="text/plain",
            help="Download the generated QIF file"
        )
        
    except Exception as e:
        st.error(f"❌ Error generating QIF file: {str(e)}")

# Tax Table Preview
if tax_df is not None:
    st.markdown('<h3 class="section-header">📊 Tax Table Preview</h3>', unsafe_allow_html=True)
    
    # Format the dataframe for display
    display_df = tax_df.copy()
    display_df['MonthlyIncome'] = display_df['MonthlyIncome'].apply(lambda x: f"${x:,.0f}")
    display_df['FederalTax'] = display_df['FederalTax'].apply(lambda x: f"${x:,.2f}")
    display_df['StateTax'] = display_df['StateTax'].apply(lambda x: f"${x:,.2f}")
    
    # Rename columns for display
    display_df = display_df.rename(columns={
        'MonthlyIncome': 'Monthly Income',
        'FederalTax': 'Federal Tax', 
        'StateTax': 'State Tax'
    })
    
    st.dataframe(display_df, width="stretch")

# Footer
st.markdown("---")
st.markdown(
    '<p style="text-align: center; color: #6b7280; font-size: 0.9rem;">Built with ❤️ using Streamlit • Simplifying tax payment management</p>', 
    unsafe_allow_html=True
)

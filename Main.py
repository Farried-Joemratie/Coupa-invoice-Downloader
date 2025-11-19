import streamlit as st
import os
import requests
import pandas as pd
import io
import zipfile
import re
from datetime import datetime
from dotenv import load_dotenv

# --- LOAD ENV VARIABLES ---
load_dotenv()

IDENTIFIER = os.getenv("IDENTIFIER")
SECRET = os.getenv("SECRET")
COUPA_INSTANCE = os.getenv("COUPA_INSTANCE")

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Coupa Invoice Downloader",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- CUSTOM CSS ---
st.markdown("""
<style>
    body {
        background-color: #FFFFFF;
    }
    .stButton>button {
        background-color: #ff5500;
        color: #ffffff;
        font-weight: bold;
        border-radius: 5px;
        border: none;
        padding: 0.6em 1.2em;
        transition: 0.3s;
    }
    .stButton>button:hover {
        background-color: #ff7733;
        color: #fff;
    }
    .top-right {
        position: absolute;
        top: 10px;
        right: 20px;
        color: #ff5500;
        font-weight: bold;
    }
    h1 {
        color: #ff5500;
    }
</style>
""", unsafe_allow_html=True)

# --- HELPER FUNCTIONS ---


def sanitize_filename(name):
    """Remove or replace characters not allowed in filenames."""
    return re.sub(r'[\\/*?:"<>|]', "_", str(name)).strip()


def get_local_zipinfo(filename):
    """Return a ZipInfo object with current timestamp."""
    zinfo = zipfile.ZipInfo(filename)
    zinfo.date_time = datetime.now().timetuple()[:6]
    return zinfo


# --- PAGE HEADER ---
st.markdown('<p class="top-right">Powered by Farried Joemratie</p>',
            unsafe_allow_html=True)
st.title("📄 Coupa Invoice Downloader")
st.write("Upload your invoice CSV and download invoice PDFs in bulk from Coupa.")


# --- SESSION STATE INIT ---
if "zip_buffer" not in st.session_state:
    st.session_state.zip_buffer = None
if "downloaded" not in st.session_state:
    st.session_state.downloaded = False
if "token" not in st.session_state:
    st.session_state.token = None


# --- AUTO-CONNECT TO COUPA ---
if not st.session_state.token:
    try:
        if not IDENTIFIER or not SECRET or not COUPA_INSTANCE:
            st.error("❌ Missing Coupa credentials. Please check your .env file.")
        else:
            st.info()
            token_url = f"https://{COUPA_INSTANCE}.coupahost.com/oauth2/token"
            token_data = {
                "grant_type": "client_credentials",
                "scope": "core.invoice.read"
            }
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            response = requests.post(token_url, auth=(IDENTIFIER, SECRET),
                                     data=token_data, headers=headers)
            response.raise_for_status()

            token = response.json().get("access_token")
            if token:
                st.session_state.token = token
                st.success()
            else:
                st.warning(
                    "⚠️ Connected but no token returned. Check API scope.")
    except Exception as e:
        st.error(f"❌ Failed to connect to Coupa: {e}")

# --- CSV UPLOAD ---
st.markdown("---")
st.subheader("📂 Upload Invoice CSV")

uploaded_file = st.file_uploader(
    "Upload your Coupa invoice CSV file", type=["csv", "txt"]
)

if uploaded_file:
    try:
        raw_csv = uploaded_file.getvalue().decode("utf-8")
        delimiter = "\t" if "\t" in raw_csv else ","
        df = pd.read_csv(io.StringIO(raw_csv), delimiter=delimiter)

        expected = ["invoice id", "invoice #", "supplier", "created date"]
        column_mapping = {}
        for key in expected:
            match = [col for col in df.columns if col.strip().lower() == key]
            if match:
                column_mapping[key] = match[0]

        st.success("✅ CSV uploaded and parsed successfully!")
        st.dataframe(df.head())

        if "invoice id" not in column_mapping:
            st.warning("⚠️ 'Invoice ID' column not found — cannot fetch PDFs.")
        else:
            invoice_ids = df[column_mapping["invoice id"]].astype(
                str).unique().tolist()

            if st.button("⬇️ Download All Invoice PDFs as ZIP"):
                if not st.session_state.token:
                    st.error("❌ Please connect to Coupa first.")
                else:
                    with st.spinner("📦 Downloading invoices..."):
                        zip_buffer = io.BytesIO()
                        failed_rows = []
                        headers = {
                            "Authorization": f"Bearer {st.session_state.token}",
                            "Accept": "application/json, */*"
                        }

                        with zipfile.ZipFile(zip_buffer, "w") as zip_file:
                            progress = st.progress(0)
                            status = st.empty()

                            for i, invoice_id in enumerate(invoice_ids):
                                invoice_id = str(
                                    invoice_id).strip().split(".")[0]

                                row = df[df[column_mapping["invoice id"]].astype(
                                    str) == invoice_id].iloc[0]

                                invoice_num = sanitize_filename(
                                    row[column_mapping["invoice #"]])
                                supplier_name = sanitize_filename(
                                    row[column_mapping["supplier"]])
                                created_date_raw = str(
                                    row[column_mapping["created date"]])
                                created_date = sanitize_filename(
                                    created_date_raw.split("T")[0]
                                    if "T" in created_date_raw else created_date_raw
                                )

                                filename = f"{supplier_name} - {invoice_num} - {created_date}.pdf"
                                scan_url = f"https://{COUPA_INSTANCE}.coupahost.com/api/invoices/{invoice_id}/retrieve_image_scan"

                                try:
                                    resp = requests.get(
                                        scan_url, headers=headers)

                                    if resp.status_code == 200:
                                        zip_file.writestr(
                                            get_local_zipinfo(filename), resp.content)
                                        status.success(
                                            f"✅ Downloaded {invoice_id}")
                                    else:
                                        status.warning(
                                            f"⚠️ Failed {invoice_id} ({resp.status_code})")

                                        # ✅ Add a unique key for each response text area
                                        st.text_area(
                                            f"Response content for {invoice_id}",
                                            resp.text,
                                            height=120,
                                            key=f"response_{invoice_id}"
                                        )

                                        failed_row = row.to_dict()
                                        failed_row["Download Status"] = f"Failed ({resp.status_code})"
                                        failed_rows.append(failed_row)

                                except Exception as e:
                                    st.error(
                                        f"❌ Error fetching invoice {invoice_id}: {e}")

                                progress.progress((i + 1) / len(invoice_ids))

                        zip_buffer.seek(0)
                        st.session_state.zip_buffer = zip_buffer
                        st.success("✅ All invoices processed successfully!")

                        if failed_rows:
                            st.warning(f"{len(failed_rows)} invoices failed.")
                            st.dataframe(pd.DataFrame(failed_rows))

    except Exception:
        st.warning("⚠️ Please upload a valid CSV file.")
        st.stop()


# --- ZIP DOWNLOAD BUTTON ---
if st.session_state.zip_buffer:
    st.markdown("---")
    st.subheader("💾 Download Ready")
    st.info("Click below to download all invoices as a ZIP file.")

    if st.download_button(
        label="📦 Download ZIP",
        data=st.session_state.zip_buffer,
        file_name="coupa_invoice_scans.zip",
        mime="application/zip"
    ):
        st.session_state.zip_buffer = None
        st.success("✅ Download complete!")
        st.rerun()


# --- FOOTER ---
st.markdown("---")
st.caption("© 2025 Coupa Invoice Downloader | Created with by Farried Joemratie")

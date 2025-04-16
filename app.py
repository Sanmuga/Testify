import streamlit as st
import google.generativeai as genai
from PIL import Image
import zipfile
import os
import tempfile
import pandas as pd
import time
import xlsxwriter
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

# ----------------------------- #
#     Streamlit Setup          #
# ----------------------------- #
st.set_page_config(page_title="Testify – UI Test Case Generator", layout="wide")
st.title("Testify")
st.write("Upload a ZIP file of webpage screenshots or enter a URL to extract UI elements and generate test cases.")

# ----------------------------- #
#     Configure Gemini          #
# ----------------------------- #
genai.configure(api_key="AIzaSyBy4K8ccNLtVJC6ELPwJ4uBZbwq8NqqdEs") 
google_model = genai.GenerativeModel(model_name="gemini-1.5-flash")

# ----------------------------- #
#     Web Element Extraction    #
# ----------------------------- #
def extract_elements_from_url(url):
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=1920,1080")
    driver = webdriver.Chrome(options=chrome_options)

    driver.get(url)
    time.sleep(2) 

    ui_elements = []

    try:
        inputs = driver.find_elements(By.XPATH, "//input[@type='text' or @type='email' or @type='password']")
        for inp in inputs:
            desc = f'Text Field: "{inp.get_attribute("placeholder") or inp.get_attribute("name")}" (Function: User input)'
            ui_elements.append(desc)

        buttons = driver.find_elements(By.XPATH, "//button | //input[@type='submit'] | //input[@type='button']")
        for btn in buttons:
            label = btn.text or btn.get_attribute("value")
            desc = f'Button: "{label}" (Function: Triggers an action)'
            ui_elements.append(desc)

        checks = driver.find_elements(By.XPATH, "//input[@type='checkbox']")
        for chk in checks:
            label = chk.get_attribute("name") or "Unnamed"
            desc = f'Checkbox: "{label}" (Function: Toggle option)'
            ui_elements.append(desc)

        radios = driver.find_elements(By.XPATH, "//input[@type='radio']")
        for rad in radios:
            label = rad.get_attribute("name") or "Unnamed"
            desc = f'Radio Button: "{label}" (Function: Select one option)'
            ui_elements.append(desc)

        selects = driver.find_elements(By.TAG_NAME, "select")
        for sel in selects:
            desc = f'Dropdown: "{sel.get_attribute("name")}" (Function: Choose from list)'
            ui_elements.append(desc)

        links = driver.find_elements(By.TAG_NAME, "a")
        for link in links[:5]:
            text = link.text.strip()
            href = link.get_attribute("href")
            desc = f'Link: "{text}" (Function: Navigates to {href})'
            ui_elements.append(desc)

    except Exception as e:
        st.error(f"Error extracting elements: {e}")
    finally:
        driver.quit()

    return "\n".join(ui_elements)

# ----------------------------- #
#     Generate Test Cases       #
# ----------------------------- #
def generate_test_cases(description, model, retries=2):
    prompt = f"""
    You are a QA expert. Given the following UI elements description, generate prioritized test scenarios and cases.

    --------------------
    {description}
    --------------------

    Format:
    | Priority | Scenario | Test Case | Expected Result |
    |----------|----------|-----------|-----------------|

    Only return the table.
    """
    for attempt in range(retries):
        try:
            response = model.generate_content(prompt)
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            st.warning(f"Attempt {attempt+1} failed: {e}")
            time.sleep(2 ** attempt)
    return "Test case generation failed."

# ----------------------------- #
#     Parse Table to DataFrame  #
# ----------------------------- #
def parse_table_to_dataframe(output_text):
    lines = output_text.splitlines()
    rows = []
    for line in lines:
        if line.startswith("|") and not line.strip().startswith("|---"):
            parts = [col.strip() for col in line.split("|")[1:-1]]
            if len(parts) == 4:
                rows.append(parts)
    return pd.DataFrame(rows, columns=["Priority", "Scenario", "Test Case", "Expected Result"])

# ----------------------------- #
#     UI Element Extraction from Image #
# ----------------------------- #
def extract_ui_elements(image_path, model):
    image = Image.open(image_path)
    prompt = """
    Analyze the provided webpage screenshot and identify the following:

    1. List all discernible UI elements: buttons, input fields, dropdowns, checkboxes, links, etc.
    2. Include labels, placeholder text, or content for each.
    3. Describe the intended functionality of each element.

    Format:
    --------------------
    UI Elements:
    - Button: "Login" (Function: Submits user login credentials)
    - Text Field: "Email Address" (Function: Allows user to input email)
    - Checkbox: "Remember me" (Function: Saves login session)
    --------------------
    Provide clean, structured output.
    """
    try:
        response = model.generate_content([image, prompt])
        return response.text.strip() if response and response.text else "UI element extraction failed."
    except Exception as e:
        return f"UI element extraction failed: {e}"

# ----------------------------- #
# File Upload & Processing     #
# ----------------------------- #
input_method = st.radio("Choose Input Method", ["Upload ZIP File", "Enter Webpage URL"])

if input_method == "Upload ZIP File":
    uploaded_zip = st.file_uploader("Upload Screenshot ZIP File", type="zip")
    
    if uploaded_zip:
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, "uploaded.zip")
            with open(zip_path, "wb") as f:
                f.write(uploaded_zip.read())

            # Extract files
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
                image_files = [
                    os.path.join(temp_dir, file)
                    for file in zip_ref.namelist()
                    if file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff'))
                ]

            st.success(f"Extracted {len(image_files)} image(s) from archive.")
            all_dfs = {}

            for img_path in image_files:
                img_name = os.path.basename(img_path)
                st.markdown(f"---\n### Processing: `{img_name}`")

                # Extract UI elements
                ui_description = extract_ui_elements(img_path, google_model)
                if "failed" in ui_description.lower():
                    st.warning(f"UI extraction failed for `{img_name}`.")
                    continue

                # Generate test cases
                table_output = generate_test_cases(ui_description, google_model)
                df = parse_table_to_dataframe(table_output)

                if not df.empty:
                    st.dataframe(df, use_container_width=True)
                    all_dfs[img_name] = df
                else:
                    st.warning(f"No test cases generated for `{img_name}`.")

            # Export to Excel
            if all_dfs:
                output_excel = os.path.join(temp_dir, "Generated_UI_Test_Cases.xlsx")
                with pd.ExcelWriter(output_excel, engine='xlsxwriter') as writer:
                    for name, df in all_dfs.items():
                        sheet_name = os.path.splitext(name)[0][:31]
                        df.to_excel(writer, index=False, sheet_name=sheet_name)

                with open(output_excel, "rb") as f:
                    st.download_button(
                        label="Download All Test Cases (Excel)",
                        data=f,
                        file_name="UI_Test_Cases_Generated.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )

elif input_method == "Enter Webpage URL":
    url = st.text_input("Enter Website URL (e.g., https://example.com):")

    if st.button("Generate Test Cases") and url:
        with st.spinner("Extracting UI elements..."):
            ui_description = extract_elements_from_url(url)

        if ui_description:
            st.subheader("🔍 Extracted UI Elements")
            st.code(ui_description)

            with st.spinner("Generating test cases..."):
                test_case_output = generate_test_cases(ui_description, google_model)

            df = parse_table_to_dataframe(test_case_output)

            if not df.empty:
                st.subheader("✅ Generated Test Cases")
                st.dataframe(df, use_container_width=True)

                # Download
                output_path = os.path.join(tempfile.gettempdir(), "test_cases.xlsx")
                df.to_excel(output_path, index=False)
                with open(output_path, "rb") as f:
                    st.download_button("📥 Download Test Cases", f, file_name="UI_Test_Cases.xlsx")
            else:
                st.warning("⚠️ No test cases generated.")
        else:
            st.error("❌ Failed to extract UI elements.")

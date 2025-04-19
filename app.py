from flask import Flask, render_template, request, send_file, jsonify, redirect, url_for
import google.generativeai as genai
from PIL import Image
import zipfile
import os
import tempfile
import pandas as pd
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ----------------------------- #
#     Configure Gemini          #
# ----------------------------- #
genai.configure(api_key="AIzaSyBy4K8ccNLtVJC6ELPwJ4uBZbwq8NqqdEs")  # Replace with your API key
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

    try:
        driver.get(url)
        time.sleep(2)

        ui_elements = []

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
        print(f"Error extracting elements: {e}")  # Log the error
        return None  # Return None to signal failure
    finally:
        driver.quit()

    return "\n".join(ui_elements) if ui_elements else None # Return None if no elements extracted

# ----------------------------- #
#     Generate Test Cases       #
# ----------------------------- #
def generate_test_cases(description, model, retries=2):
    if not description:
        return None #Handles empty description cases
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
            print(f"Attempt {attempt+1} failed: {e}") # Log the error
            time.sleep(2 ** attempt)
    return None #Returns none if all retries fail

# ----------------------------- #
#     Parse Table to DataFrame  #
# ----------------------------- #
def parse_table_to_dataframe(output_text):
    if not output_text:
        return pd.DataFrame()  # Return an empty DataFrame for empty output
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
    try:
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
        response = model.generate_content([image, prompt])
        return response.text.strip() if response and response.text else None # Return None if no response
    except Exception as e:
        print(f"UI element extraction failed: {e}") # Log the error
        return None # Return None on failure

# ----------------------------- #
# File Upload & Processing     #
# ----------------------------- #

def process_zip_file(zip_file):
    all_dfs = {}
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = os.path.join(temp_dir, "uploaded.zip")
        zip_file.save(zip_path) #save the uploaded file
        # Extract files
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
                image_files = [
                    os.path.join(temp_dir, file)
                    for file in zip_ref.namelist()
                    if file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff'))
                ]
        except zipfile.BadZipFile:
            return None, "Invalid ZIP file."  # Return error message if the zip file is corrupt

        if not image_files:
            return None, "No images found in the ZIP file."

        for img_path in image_files:
            img_name = os.path.basename(img_path)
            # Extract UI elements
            ui_description = extract_ui_elements(img_path, google_model)
            if not ui_description:
                print(f"UI extraction failed for {img_name}")
                continue #Skip to the next image

            # Generate test cases
            table_output = generate_test_cases(ui_description, google_model)
            df = parse_table_to_dataframe(table_output)
            if not df.empty:
                all_dfs[img_name] = df
            else:
                print(f"No test cases generated for {img_name}")
        if all_dfs:
            output_excel = os.path.join(temp_dir, "Generated_UI_Test_Cases.xlsx")
            try:
                with pd.ExcelWriter(output_excel, engine='xlsxwriter') as writer:
                    for name, df in all_dfs.items():
                        sheet_name = os.path.splitext(name)[0][:31]
                        df.to_excel(writer, index=False, sheet_name=sheet_name)
            except Exception as e:
                print(f"Error writing to Excel: {e}") # Log the excel writing error
                return None, "Error generating Excel file."  #handle Excel writer error
            return output_excel, all_dfs, None #Return excel path, dfs and no error
        else:
            return None, None, "No test cases generated for any images." #handle cases where no test cases generated.
def process_url(url):
    ui_description = extract_elements_from_url(url)
    if not ui_description:
        return None, None, "Failed to extract UI elements from URL."

    test_case_output = generate_test_cases(ui_description, google_model)
    df = parse_table_to_dataframe(test_case_output)
    if df.empty:
        return None, None, "No test cases generated."

    output_path = os.path.join(tempfile.gettempdir(), "test_cases.xlsx")
    try:
        df.to_excel(output_path, index=False)
    except Exception as e:
        print(f"Error writing to Excel: {e}")  # Log the excel writing error
        return None, None, "Error generating Excel file."
    return output_path, df, None #Return excel path, dataframe and no error


@app.route('/', methods=['GET'])
def home():
    return render_template('home.html')


@app.route('/test_cases', methods=['GET', 'POST'])
def index():
    excel_file_path = None
    error_message = None
    all_dfs = None  # Store the DataFrames for displaying tables
    processing = False # Flag to indicate processing
    if request.method == 'POST':
        processing = True  # Set processing flag when the form is submitted
        input_method = request.form.get('input_method')

        if input_method == 'zip_upload':
            zip_file = request.files.get('zip_file')
            if zip_file:
                filename = secure_filename(zip_file.filename)  # Sanitize filename
                if not filename.endswith('.zip'):
                    error_message = "Invalid file type. Please upload a ZIP file."
                    processing = False  # Reset processing if there's an error
                else:
                    excel_file_path, all_dfs, error_message = process_zip_file(zip_file)
                    processing = False  # Reset processing after processing is complete
        elif input_method == 'url_input':
            url = request.form.get('url')
            if url:
                excel_file_path,  df, error_message = process_url(url)
                if df is not None:
                  all_dfs = {"Generated_UI_Test_Cases": df} #Create a dictionary to make it compatible with the display logic
                processing = False  # Reset processing after processing is complete


    return render_template('index.html', excel_file_path=excel_file_path, error_message=error_message, all_dfs=all_dfs, processing=processing)


@app.route('/download/<path:filename>')
def download_file(filename):
    try:
        return send_file(filename, as_attachment=True)
    except FileNotFoundError:
        return "File not found", 404
    except Exception as e:
        print(f"Error during download: {e}")  # Log the error
        return "Error during download", 500

if __name__ == '__main__':
    app.run(debug=True)

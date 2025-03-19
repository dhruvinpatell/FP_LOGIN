from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
import pandas as pd
import time
import traceback
from filelock import FileLock
from multiprocessing import Pool
import os

# Dynamically set Excel file path for GitHub Actions
FILE_PATH = os.path.join(os.getcwd(), "newcomm.xlsx")

def save_to_excel(no):
    """Save updates to the Excel file without removing other sheets."""
    lock_path = f"{FILE_PATH}.lock"
    lock = FileLock(lock_path)
    max_retries = 5

    for attempt in range(max_retries):
        try:
            with lock.acquire(timeout=10):
                # Read existing sheets
                with pd.ExcelFile(FILE_PATH) as xls:
                    existing_sheets = {sheet: xls.parse(sheet) for sheet in xls.sheet_names}

                # Modify only the relevant sheet
                users = existing_sheets.get("2.all account", pd.DataFrame())
                users.loc[users["no"] == no, "fs"] = "D"

                # Save all sheets back
                with pd.ExcelWriter(FILE_PATH, engine="openpyxl") as writer:
                    for sheet_name, df in existing_sheets.items():
                        df.to_excel(writer, sheet_name=sheet_name, index=False)
                
                return
        except Exception as e:
            print(f"Attempt {attempt + 1}: Unable to save data for {no} due to: {e}")
            time.sleep(3)

    print(f"Failed to save data for {no} after {max_retries} retries.")

def setup_driver(profile):
    """Set up a single Selenium WebDriver per process."""
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Run in headless mode for GitHub
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument(f"--user-data-dir={profile}")  # Use temp profile
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    # Updated path for chromedriver in GitHub Actions
    service = Service("/usr/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=chrome_options)

    return driver

def login_process(profile, user_list):
    """Handles multiple logins using the same WebDriver instance per process."""
    driver = setup_driver(profile)
    wait = WebDriverWait(driver, 20)

    for user_info in user_list:
        no, username, password = user_info
        try:
            driver.get("https://app.fundingpips.com/competitions/efdffce5-2461-4474-9ec4-cdcfa8e843db")
            wait.until(EC.visibility_of_element_located((By.ID, "email"))).send_keys(username)
            driver.find_element(By.ID, "password").send_keys(password)
            time.sleep(2)

            max_attempts = 0
            while True:
                try:
                    sign_in_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[text()='Sign in']")))
                    sign_in_button.click()

                    # Check for either Account or Join button
                    wait.until(EC.any_of(
                        EC.visibility_of_element_located((By.XPATH, "//button[contains(@class, 'flex items-center') and div[text()='Account']]")),
                        EC.visibility_of_element_located((By.XPATH, "//button[div[text()='Join']]"))
                    ))
                    break  # Login success
                except TimeoutException:
                    if max_attempts < 5:
                        max_attempts += 1
                        continue
                    print(f"Login failed for {username}")
                    raise StopIteration

            if driver.find_elements(By.XPATH, "//button[div[text()='Join']]"):
                driver.find_element(By.XPATH, "//button[div[text()='Join']]").click()
                WebDriverWait(driver, 120).until(EC.element_to_be_clickable((By.XPATH, "//button[text()='Confirm']"))).click()

                if wait.until(EC.presence_of_element_located((By.XPATH, "//div[text()='Competition Joined successfully']"))):
                    print(f"Account successfully joined for {no}: {username}")
                    save_to_excel(no)

            if driver.find_elements(By.XPATH, "//button[contains(@class, 'flex items-center') and div[text()='Account']]"):
                print(f"Already joined competition for {no} {username}")
                save_to_excel(no)

            # Logout to continue with next user
            logout_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'focus:ring-3') and .//div[text()='Logout']]")))
            logout_button.click()
            driver.delete_all_cookies()
            wait.until(EC.visibility_of_element_located((By.ID, "email")))

        except Exception as e:
            print(f"Error processing {no} {username}: {traceback.format_exc()}")
            try:
                logout_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'focus:ring-3') and .//div[text()='Logout']]")))
                logout_button.click()
                driver.delete_all_cookies()
                wait.until(EC.visibility_of_element_located((By.ID, "email")))
            except:
                pass

    driver.quit()

if __name__ == "__main__":
    profile_paths = [
        "/tmp/chrome-profile-1",
        "/tmp/chrome-profile-2"
    ]  # Use temp paths for Chrome profiles in GitHub Actions

    # Load Excel sheet
    users = pd.read_excel(FILE_PATH, sheet_name="2.all account")
    users_to_process = users[users["fs"] != "D"]

    user_list = list(users_to_process[['no', 'username', 'password']].itertuples(index=False, name=None))

    # Divide users among profiles evenly
    num_profiles = len(profile_paths)
    user_chunks = [user_list[i::num_profiles] for i in range(num_profiles)]

    # Run in parallel with multiprocessing
    with Pool(processes=num_profiles) as pool:
        pool.starmap(login_process, zip(profile_paths, user_chunks))

    print("✅ All logins completed.")

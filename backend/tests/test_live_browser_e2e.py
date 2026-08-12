"""
Live Playwright Browser End-to-End Test Suite.

Simulates real user browser interactions on the Netlify live web application:
https://amipi-nacha.netlify.app/
"""
import os
import pytest
from playwright.async_api import async_playwright

BASE_URL = "https://amipi-nacha.netlify.app/"
EXCEL_PATH = "/home/bocchi_277/Programming_files/AmipiWork/FirstProject/PAYMENTS 20260730.xlsx"


@pytest.mark.asyncio
async def test_live_browser_e2e_full_workflow():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 960})
        page = await context.new_page()

        print("\n--- [E2E STEP 1] Navigating to Live Web App ---")
        await page.goto(BASE_URL, wait_until="domcontentloaded")
        await page.wait_for_selector("#loginScreen", timeout=15000)

        # Check if already logged in or needs login
        is_login_visible = await page.is_visible("#loginScreen")
        if is_login_visible:
            print("--- [E2E STEP 2] Logging in as Admin ---")
            await page.fill("#loginUsername", "admin")
            await page.fill("#loginPassword", "admin123")
            await page.click("#loginSubmitBtn")
            await page.wait_for_selector("#appShell", timeout=15000)

        print("--- [E2E STEP 3] Spreadsheet Upload & Invoice Breakdown Modal Test ---")
        await page.set_input_files("#fileInput", EXCEL_PATH)
        await page.click("#uploadBtn")
        await page.wait_for_selector("#validPaymentsTableBody tr", timeout=25000)

        rows = await page.query_selector_all("#validPaymentsTableBody tr")
        assert len(rows) > 0, "No valid payment rows parsed from spreadsheet"

        # Check for 3 Invoices breakdown button
        breakdown_btn = await page.query_selector("button:has-text('Invoices 🔍')")
        assert breakdown_btn is not None, "Invoice breakdown badge button not found in Batch 1 table"

        await breakdown_btn.click()
        await page.wait_for_selector("#invoiceBreakdownModal.active", timeout=5000)

        # Check breakdown modal contents
        modal_visible = await page.is_visible("#invoiceBreakdownModal")
        assert modal_visible, "invoiceBreakdownModal is not visible"

        modal_title = await page.text_content("#breakdownVendorTitle")
        assert "BRINKS" in modal_title or "Breakdown" in modal_title

        modal_rows = await page.query_selector_all("#breakdownTableBody tr")
        assert len(modal_rows) >= 3, f"Expected at least 3 sub-bill invoice rows, found {len(modal_rows)}"

        print("--> Breakdown Modal Verified Successfully! Closing Modal...")
        await page.click("#closeBreakdownModalBtn")
        await page.wait_for_selector("#invoiceBreakdownModal:not(.active)", timeout=5000)

        print("--- [E2E STEP 4] Manual Payment Entry (Batch 2) ---")
        await page.select_option("#manualVendorSelect", index=1)
        await page.fill("#manualAmount", "250.00")
        await page.fill("#manualIdNumber", "MAN-REF-001")
        await page.click("#addManualEntryBtn")
        await page.wait_for_selector("#manualPaymentsTableBody tr", timeout=5000)

        print("--- [E2E STEP 5] Generating NACHA File ---")
        await page.click("#generateNachaBtn")
        await page.wait_for_selector("#nachaOutputCard", timeout=15000)

        nacha_text = await page.text_content("#nachaPreview")
        assert len(nacha_text.strip()) > 0, "Generated NACHA text is empty"

        lines = [l for l in nacha_text.splitlines() if l.strip()]
        for idx, line in enumerate(lines):
            assert len(line) == 94, f"NACHA Line {idx+1} length {len(line)} != 94: '{line}'"

        print("--> NACHA File Generated & 94-Char Width Verified!")

        print("--- [E2E STEP 6] Testing Vendors Master Book Tab ---")
        await page.click("button[data-view='vendors']")
        await page.wait_for_selector("#vendorsTableBody tr", timeout=10000)

        v_rows = await page.query_selector_all("#vendorsTableBody tr")
        assert len(v_rows) > 0, "No vendors found in Vendor Master Book"

        print("--- [E2E STEP 7] Testing Payment History & Breakdown Modal Tab ---")
        await page.click("button[data-view='history']")
        await page.wait_for_selector("#historyTableBody tr", timeout=10000)

        h_rows = await page.query_selector_all("#historyTableBody tr")
        assert len(h_rows) > 0, "No remittance records found in Payment History tab"

        # Check for history breakdown badge if present
        h_breakdown_btn = await page.query_selector("#historyTableBody button:has-text('Invoices 🔍')")
        if h_breakdown_btn:
            await h_breakdown_btn.click()
            await page.wait_for_selector("#invoiceBreakdownModal.active", timeout=5000)
            assert await page.is_visible("#invoiceBreakdownModal")
            await page.click("#closeBreakdownModalBtn")

        print("--- [E2E STEP 8] Testing Admin Approvals Tab ---")
        await page.click("button[data-view='admin-approvals']")
        await page.wait_for_selector("#view-admin-approvals", timeout=5000)

        print("--- [E2E STEP 9] Testing Audit Trail Logs Tab ---")
        await page.click("button[data-view='audit-logs']")
        await page.wait_for_selector("#view-audit-logs", timeout=5000)

        print("--- [E2E STEP 10] Testing Help & Templates Tab ---")
        await page.click("button[data-view='help']")
        await page.wait_for_selector("#view-help", timeout=5000)

        await browser.close()
        print("\n🎉 ALL E2E BROWSER STEPS PASSED 100% CLEANLY!")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_live_browser_e2e_full_workflow())

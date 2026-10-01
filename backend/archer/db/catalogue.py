"""
What the dataset contains, described for people and for prompts.

One home for these facts: the guide in the React app reads them through
/api/schema, and the conversational prompts read them directly, so the two
cannot describe the data differently.
"""

# Columns the model is told to return by default, and which most answers are
# built from. Surfaced separately so the guide reflects what a user will
# actually see rather than all 37 columns undifferentiated. Must match rule 1
# of prompts/sql_generator.md; a test holds the two together.
COMMON_COLUMNS = {
    "customer_name",
    "document_date",
    "document_number",
    "item_group",
    "item_description",
    "revenue",
    "end_user_company_name",
    "quantity",
}

# Values worth knowing before asking a question. These mirror the COLUMN VALUES
# section of the SQL prompt: if a user has to guess whether a flag is 'Yes' or
# 'Y', so did the model, and that was a real source of wrong answers.
KNOWN_VALUES = {
    "document_type": ["Invoice", "Credit"],
    "item_group": ["IBM SOFT", "IBM SERV", "IBM CCHW"],
    "multi_year_deal_flag_so": ["Yes", "No"],
}

# One line per column, for a visitor rather than a database administrator.
# Written from scripts/generate_dataset.py, so each says what the column holds
# in this dataset - including the three that are always empty, which a visitor
# would otherwise ask about and get nothing back. A test fails if a column in
# the generator has no entry here.
COLUMN_DESCRIPTIONS = {
    "document_type": "Invoice for a sale, or Credit for a refund. Credit lines carry negative revenue and quantity.",
    "customer_number": "The partner's account number.",
    "customer_name": "The partner (reseller) that placed the order. \"Customer\" and \"partner\" both mean this.",
    "document_date": "Date of the invoice or credit.",
    "document_number": "The invoice or credit number. One document is one deal, and can span several lines.",
    "sales_order_number": "The sales order the document was raised from.",
    "customer_order_number": "The partner's own order reference.",
    "item_group": "Product family: IBM SOFT (software), IBM SERV (services) or IBM CCHW (hardware).",
    "vendor_number": "Account number of the IBM entity supplying the item.",
    "vendor_name": "The IBM entity supplying the item, such as IBM United Kingdom Limited.",
    "item_number": "Part number of the item sold.",
    "item_description": "Name of the IBM product or service sold.",
    "multi_year_deal_flag_so": "Yes if the order covers more than one year, otherwise No.",
    "line_number": "Position of the line within its document.",
    "item_sub_group_1": "Product sub-category code.",
    "item_sub_group_2": "Broader product category code.",
    "item_sub_group_3": "Further product sub-category. Empty in this dataset.",
    "item_sub_group_5": "Further product sub-category. Empty in this dataset.",
    "brand": "IBM brand code: IBA or IBW.",
    "sub_brand": "IBM sub-brand code. SAA on every row.",
    "quantity": "Units on the line. Negative on credits.",
    "revenue": "Value of the line in pounds. Negative on credits.",
    "end_user_company_name": "The organisation the partner sold on to, which uses the product.",
    "end_user_address": "The end user's address.",
    "end_user_post_code": "The end user's postcode.",
    "end_user_country": "The end user's country. GBR on every row.",
    "purchase_order_number": "The purchase order placed with the vendor for this deal.",
    "customer_address": "The partner's address.",
    "customer_city": "The partner's city.",
    "customer_post_code": "The partner's postcode.",
    "customer_country": "The partner's country. GBR on every row.",
    "serial_numbers": "Hardware serial numbers. Empty in this dataset.",
    "contract_start_date": "Start of the support or subscription period the line covers.",
    "contract_end_date": "End of the support or subscription period the line covers.",
    "vendor_quotation_number": "IBM's quote reference for the deal.",
    "maintenance_contract_number": "The maintenance or support contract reference.",
    "renewal_term_months": "Renewal term in months (1, 3, 12, 24 or 36), or - where none applies.",
}

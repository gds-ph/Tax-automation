"""Shared contact details for company filing setup."""
COMPANY_CONTACT = {
    'email_address': 'starlightebirforms@gmail.com',
    'telephone_number': '0272554774',
}

DEFAULT_RDO_EMAIL = 'contact_us@bir.gov.ph'

TEST_CLIENT_CODES = frozenset({'DUMMY-CLIENT-001', 'TEST-639848605-00000', 'TEST-639852610-00000'})
TEST_CONTACT = {'email_address': 'automation-test@example.invalid', 'telephone_number': '00000000000'}

def contact_for_client(client_code):
    return dict(TEST_CONTACT if client_code in TEST_CLIENT_CODES else COMPANY_CONTACT)

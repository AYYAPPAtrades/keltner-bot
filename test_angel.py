
import pyotp
from SmartApi import SmartConnect

# നിങ്ങളുടെ ക്രഡൻഷ്യലുകൾ
API_KEY = "Qm1mu8xU"
CLIENT_CODE = "AACM196001"
PIN = "4099"
TOTP_SECRET = "XXWTRAQWY6B4XGDBHD2YAJRVJE"

def test_login():
    try:
        print("Testing Angel One Login...")
        smart_api = SmartConnect(api_key=API_KEY)
        
        # തത്സമയം 6-അക്ക TOTP ജനറേറ്റ് ചെയ്യുന്നു
        totp = pyotp.TOTP(TOTP_SECRET).now()
        print(f"Generated Live TOTP: {totp}")
        
        # ലോഗിൻ സെഷൻ ഉണ്ടാക്കുന്നു
        data = smart_api.generateSession(CLIENT_CODE, PIN, totp)
        
        if data and data.get("status"):
            print("✅ LOGIN SUCCESSFUL! Angel One API കണക്ഷൻ വിജയകരമാണ്.")
            
            # അക്കൗണ്ട് പ്രൊഫൈൽ ഡാറ്റ വെരിഫൈ ചെയ്യുന്നു
            profile = smart_api.getProfile(data['data']['refreshToken'])
            client_name = profile['data']['name']
            print(f"👤 Account Holder Name: {client_name}")
            print(f"🆔 Client ID: {profile['data']['clientcode']}")
            print("🎉 നിങ്ങളുടെ എല്ലാ API Secret-കളും 100% കൃത്യമാണ്!")
        else:
            print(f"❌ LOGIN FAILED: {data.get('message')}")
            
    except Exception as e:
        print(f"⚠️ Error: {e}")

if __name__ == "__main__":
    test_login()

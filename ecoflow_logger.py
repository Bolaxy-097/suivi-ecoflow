import os
import time
import random
import hmac
import hashlib
import requests
from datetime import datetime

# ============================================================
# CONFIGURATION DEPUIS LES VARIABLES D'ENVIRONNEMENT
# ============================================================
ACCESS_KEY = os.getenv("ECOFLOW_ACCESS_KEY")
SECRET_KEY = os.getenv("ECOFLOW_SECRET_KEY")
SN = os.getenv("ECOFLOW_SN")
GOOGLE_WEBHOOK_URL = os.getenv("GOOGLE_SHEET_WEBHOOK_URL")

BASE_URL = "https://api-e.ecoflow.com"

# ============================================================
# FONCTION DE SIGNATURE
# ============================================================
def hmac_sha256(text, secret):
    return hmac.new(
        secret.encode("utf-8"),
        text.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

def make_signature(params, headers):
    param_string = ""
    if params:
        sorted_params = sorted(params.items())
        param_string = "&".join(f"{k}={v}" for k, v in sorted_params)

    header_string = "&".join(f"{k}={v}" for k, v in sorted(headers.items()))
    sign_string = (param_string + "&" + header_string) if param_string else header_string
    return hmac_sha256(sign_string, SECRET_KEY)

def ecoflow_get(endpoint, params=None):
    if params is None:
        params = {}

    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))

    headers = {
        "accessKey": ACCESS_KEY,
        "nonce": nonce,
        "timestamp": timestamp
    }

    headers["sign"] = make_signature(params, headers)
    url = BASE_URL + endpoint

    try:
        res = requests.get(url, headers=headers, params=params, timeout=20)
        return res.json() if res.status_code == 200 else None
    except Exception as e:
        print("Erreur de connexion API EcoFlow:", e)
        return None

# ============================================================
# RÉCUPÉRATION ET EXTRACTION DES DONNÉES
# ============================================================
def main():
    # 1. Vérifier si l'appareil est en ligne
    device_list_res = ecoflow_get("/iot-open/sign/device/list")
    is_online = False
    if device_list_res and str(device_list_res.get("code")) == "0":
        devices = device_list_res.get("data", [])
        for dev in devices:
            if dev.get("sn") == SN:
                is_online = (dev.get("online") == 1)

    # 2. Récupérer l'ensemble des quotas
    quota_res = ecoflow_get("/iot-open/sign/device/quota/all", {"sn": SN})
    
    if not quota_res or str(quota_res.get("code")) != "0":
        print("❌ Impossible de récupérer les métriques.")
        return

    data = quota_res.get("data", {})

    # Extraction des valeurs
    soc = data.get("bmsMaster.soc", 0)
    temp = data.get("bmsMaster.temp", 0)
    cycles = data.get("bmsMaster.cycles", 0)
    input_watts = data.get("bmsMaster.inputWatts", 0)
    output_watts = data.get("bmsMaster.outputWatts", 0)

    # Tension Entrée / Sortie AC (converties de mV ou V selon le champ)
    raw_in_volt = data.get("inv.inVolt", 0)
    raw_out_volt = data.get("inv.outVolt", 0) or data.get("inv.invOutVolt", 0)
    in_volt = round(raw_in_volt / 1000.0, 1) if raw_in_volt > 1000 else raw_in_volt
    out_volt = round(raw_out_volt / 1000.0, 1) if raw_out_volt > 1000 else raw_out_volt

    # États logiques
    ac_plugged = (in_volt > 50) or (data.get("pd.iconAcIn", 0) == 1)
    inverter_on = (data.get("inv.cfgAcEnabled", 0) == 1) or (data.get("pd.iconAcOut", 0) == 1)
    
    # Mode charge rapide (si charge lente non configurée)
    slow_chg_watts = data.get("inv.cfgSlowChgWatts", 0)
    fast_mode = (slow_chg_watts == 0) or (data.get("inv.cfgFastChgWatts", 0) > 0)

    # Puissance des panneaux solaires
    solar_watts = data.get("mppt.inWatts", 0)

    # Puissance cumulée des ports USB (USB Standard + QC + Type-C)
    usb_watts = (
        data.get("pd.usb1Watts", 0) +
        data.get("pd.usb2Watts", 0) +
        data.get("pd.qcUsb1Watts", 0) +
        data.get("pd.qcUsb2Watts", 0) +
        data.get("pd.typec1Watts", 0) +
        data.get("pd.typec2Watts", 0)
    )

    # Date et heure au format local
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Payload à envoyer à Google Sheets
    payload = {
        "datetime": now_str,
        "online": is_online,
        "soc": soc,
        "ac_plugged": ac_plugged,
        "input_watts": input_watts,
        "output_watts": output_watts,
        "inverter_on": inverter_on,
        "fast_mode": fast_mode,
        "in_volt": in_volt,
        "out_volt": out_volt,
        "usb_watts": usb_watts,
        "solar_watts": solar_watts,
        "temp": temp,
        "cycles": cycles
    }

    print("Envoi des données vers Google Sheets...")
    print(payload)

    response = requests.post(GOOGLE_WEBHOOK_URL, json=payload, timeout=15)
    print("Réponse Google Sheets :", response.text)

if __name__ == "__main__":
    main()

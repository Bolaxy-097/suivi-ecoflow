import os
import time
import random
import hmac
import hashlib
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# ============================================================
# CONFIGURATION
# ============================================================
ACCESS_KEY = os.getenv("ECOFLOW_ACCESS_KEY")
SECRET_KEY = os.getenv("ECOFLOW_SECRET_KEY")
SN = os.getenv("ECOFLOW_SN")
GOOGLE_WEBHOOK_URL = os.getenv("GOOGLE_SHEET_WEBHOOK_URL")

BASE_URL = "https://api-e.ecoflow.com"

# ============================================================
# FONCTIONS API
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
        print("Erreur API EcoFlow :", e)
        return None

# ============================================================
# MAIN
# ============================================================
def main():
    # 1. État en ligne
    device_list_res = ecoflow_get("/iot-open/sign/device/list")
    is_online = False
    if device_list_res and str(device_list_res.get("code")) == "0":
        for dev in device_list_res.get("data", []):
            if dev.get("sn") == SN:
                is_online = (dev.get("online") == 1)

    # 2. Récupération des données
    quota_res = ecoflow_get("/iot-open/sign/device/quota/all", {"sn": SN})
    if not quota_res or str(quota_res.get("code")) != "0":
        print("❌ Impossible de récupérer les données.")
        return

    data = quota_res.get("data", {})

    # Batterie, Température et Cycles
    soc = data.get("bmsMaster.soc", 0)
    temp = data.get("bmsMaster.temp", 0)
    cycles = data.get("bmsMaster.cycles", 0)

    # Puissances d'entrée et de sortie (Somme PD ou BMS/INV)
    input_watts = data.get("pd.wattsInSum")
    if input_watts is None or input_watts == 0:
        input_watts = data.get("bmsMaster.inputWatts", 0) or data.get("inv.inWatts", 0)

    output_watts = data.get("pd.wattsOutSum")
    if output_watts is None or output_watts == 0:
        output_watts = data.get("bmsMaster.outputWatts", 0) or data.get("inv.outWatts", 0)

    # Tensions Entrée / Sortie AC
    raw_in_volt = data.get("inv.inVol", 0) or data.get("inv.acInVol", 0)
    raw_out_volt = data.get("inv.invOutVol", 0) or data.get("inv.outVol", 0)

    in_volt = round(raw_in_volt / 1000.0, 1) if raw_in_volt > 1000 else float(raw_in_volt)
    out_volt = round(raw_out_volt / 1000.0, 1) if raw_out_volt > 1000 else float(raw_out_volt)

    # Onduleur AC
    # Onduleur AC (Détection stricte du bouton AC)
    ac_enabled = data.get("inv.cfgAcEnabled", 0) == 1
    ac_watts = data.get("inv.outputWatts", 0) or data.get("inv.invOutWatts", 0)

    inverter_on = ac_enabled or (ac_watts > 5)

    # Secteur Branché
    ac_plugged = (in_volt > 50) or (input_watts > 10) or (data.get("pd.iconAcIn", 0) == 1)

    # Mode Charge Rapide (Fast Charge)
    slow_chg_watts = data.get("inv.cfgSlowChgWatts", 0)
    net_charge_watts = max(0, input_watts - output_watts)
    fast_mode = True if (not ac_plugged or net_charge_watts > (slow_chg_watts + 150)) else False

    # Solaire & USB
    solar_watts = data.get("mppt.inWatts", 0) or data.get("mppt.pwrIn", 0)
    usb_watts = (
        data.get("pd.usb1Watts", 0) +
        data.get("pd.usb2Watts", 0) +
        data.get("pd.qcUsb1Watts", 0) +
        data.get("pd.qcUsb2Watts", 0) +
        data.get("pd.typec1Watts", 0) +
        data.get("pd.typec2Watts", 0)
    )

    # Heure locale Kinshasa (UTC+1)
    now_str = datetime.now(ZoneInfo("Africa/Kinshasa")).strftime("%Y-%m-%d %H:%M:%S")

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

    print("Envoi vers Google Sheets :", payload)
    res = requests.post(GOOGLE_WEBHOOK_URL, json=payload, timeout=15)
    print("Réponse Google Sheets :", res.text)

if __name__ == "__main__":
    main()

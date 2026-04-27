from flask import Flask, jsonify
import subprocess

app = Flask(__name__)

SCRIPTS = {
    "etig":   "notificador_etig.py",
    "acadeu": "notificador_acadeu_nuestra_tierra.py"
}


@app.route('/<service>', methods=['POST'])
def trigger_notifier(service):
    if service not in SCRIPTS:
        return jsonify({"error": "Servicio no encontrado"}), 404

    script_path = SCRIPTS[service]
    try:
        subprocess.Popen(["python3", script_path])
        return jsonify({"status": f"Ejecución de {service} iniciada"}), 202
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5550)

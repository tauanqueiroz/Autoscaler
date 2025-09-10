import os
import requests
import docker
import time
from datetime import datetime, timedelta

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
SERVICE_NAME = os.getenv("SERVICE_NAME")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 30))

MIN_REPLICAS = int(os.getenv("MIN_REPLICAS", 2))
MAX_REPLICAS = int(os.getenv("MAX_REPLICAS", 10))

SCALE_UP_QUERY = os.getenv("SCALE_UP_QUERY")
SCALE_UP_THRESHOLD = float(os.getenv("SCALE_UP_THRESHOLD", 70.0))
SCALE_UP_DURATION = int(os.getenv("SCALE_UP_DURATION", 300)) # segundos

SCALE_DOWN_QUERY = os.getenv("SCALE_DOWN_QUERY")
SCALE_DOWN_THRESHOLD = float(os.getenv("SCALE_DOWN_THRESHOLD", 30.0))
SCALE_DOWN_DURATION = int(os.getenv("SCALE_DOWN_DURATION", 600)) # em segundos

last_scale_up_time = datetime.min
last_scale_down_time = datetime.min

client = docker.from_env()

def get_metric_from_prometheus(query):
    try:
        response = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={'query': query})
        response.raise_for_status()
        result = response.json()['data']['result']
        if result:
            return float(result[0]['value'][1])
        return 0.0
    except Exception as e:
        print(f"Erro ao consultar Prometheus: {e}")
        return None

def main():
    print(">>> Iniciando Autoscaler para o serviço:", SERVICE_NAME)

    high_cpu_since = None
    low_cpu_since = None

    while True:
        try:
            service = client.services.get(SERVICE_NAME)
            current_replicas = service.attrs['Spec']['Mode']['Replicated']['Replicas']
            print(f"\n--- Verificando às {datetime.now().isoformat()} ---")
            print(f"Réplicas atuais: {current_replicas}")

            cpu_usage = get_metric_from_prometheus(SCALE_UP_QUERY)
            if cpu_usage is None:
                time.sleep(CHECK_INTERVAL)
                continue

            print(f"Uso médio de CPU: {cpu_usage:.2f}%")

            if cpu_usage > SCALE_UP_THRESHOLD:
                if high_cpu_since is None:
                    high_cpu_since = datetime.now()

                duration_in_high_cpu = (datetime.now() - high_cpu_since).total_seconds()
                print(f"CPU acima do limiar por {duration_in_high_cpu:.0f}s (necessário {SCALE_UP_DURATION}s)")

                if duration_in_high_cpu >= SCALE_UP_DURATION:
                    if current_replicas < MAX_REPLICAS:
                        new_replicas = current_replicas + 1
                        print(f"!!! ESCALANDO PARA CIMA: {current_replicas} -> {new_replicas} réplicas !!!")
                        service.scale(new_replicas)
                        high_cpu_since = None # Reseta o timer
                    else:
                        print("Já no número máximo de réplicas.")
                low_cpu_since = None # Reseta o timer de baixa CPU

            elif cpu_usage < SCALE_DOWN_THRESHOLD:
                if low_cpu_since is None:
                    low_cpu_since = datetime.now()

                duration_in_low_cpu = (datetime.now() - low_cpu_since).total_seconds()
                print(f"CPU abaixo do limiar por {duration_in_low_cpu:.0f}s (necessário {SCALE_DOWN_DURATION}s)")

                if duration_in_low_cpu >= SCALE_DOWN_DURATION:
                    if current_replicas > MIN_REPLICAS:
                        new_replicas = current_replicas - 1
                        print(f"!!! ESCALANDO PARA BAIXO: {current_replicas} -> {new_replicas} réplicas !!!")
                        service.scale(new_replicas)
                        low_cpu_since = None # Reset timer
                    else:
                        print("Já no número mínimo de réplicas.")
                high_cpu_since = None # Reset timer de alta CPU

            else:
                print("CPU em estado normal. Resetando timers.")
                high_cpu_since = None
                low_cpu_since = None

        except Exception as e:
            print(f"Erro no loop principal: {e}")

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    if not all([SERVICE_NAME, SCALE_UP_QUERY, SCALE_DOWN_QUERY]):
        raise ValueError("Variáveis de ambiente essenciais (SERVICE_NAME, SCALE_UP_QUERY, SCALE_DOWN_QUERY) não foram definidas.")
    main()

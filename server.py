import socket
import threading

SERVER_IP = '0.0.0.0'
SERVER_PORT = 9999

# Mapping: mac -> { 'ip': ..., 'number': ..., 'received': ... }
mapping = {
    "0A:8C:52:B1:1C:D2": {"ip": None, "number": 105, "received": False},
    # "14:AC:60:CB:16:7F": {"ip": None, "number": 136, "received": False},
    "AA:BB:CC:DD:EE:03": {"ip": None, "number": 103, "received": False},
}
used_numbers = set()

def handle_request(data, addr, server_sock):
    global mapping, used_numbers
    parts = data.decode().strip().split(',')
    command = parts[0]

    if command == "REGISTER" and len(parts) == 2:
        mac = parts[1]
        ip = addr[0]
        if mac in mapping:
            mapping[mac]['ip'] = ip
            mapping[mac]['received'] = True
            print(f"[+] Registered {mac} with IP {ip} and number {mapping[mac]['number']}")
            response = f"REGISTERED,{mapping[mac]['number']}"
            server_sock.sendto(response.encode(), addr)
        else:
            available_numbers = [n for n in range(100, 200) if n not in used_numbers]
            if not available_numbers:
                server_sock.sendto(b"NO_NUMBERS_LEFT", addr)
                print("[!] No numbers left for new MAC registration.")
                return
            assigned_number = available_numbers[0]
            used_numbers.add(assigned_number)
            mapping[mac] = {"ip": ip, "number": assigned_number, "received": True}
            print(f"[+] New MAC {mac} registered with number {assigned_number} and IP {ip}")
            response = f"REGISTERED,{assigned_number}"
            server_sock.sendto(response.encode(), addr)

    elif command == "GET" and len(parts) == 2:
        try:
            num = int(parts[1])
            for mac, info in mapping.items():
                if info['number'] == num and info['received']:
                    response = f"FOUND,{info['ip']}"
                    server_sock.sendto(response.encode(), addr)
                    return
            server_sock.sendto(b"NOT_FOUND", addr)
        except ValueError:
            server_sock.sendto(b"NOT_FOUND", addr)

    elif command == "WHO" and len(parts) == 2:
        ip = parts[1]
        for mac, info in mapping.items():
            if info['ip'] == ip:
                response = f"FOUND,{info['number']}"
                server_sock.sendto(response.encode(), addr)
                return
        server_sock.sendto(b"NOT_FOUND", addr)

    else:
        server_sock.sendto(b"INVALID_COMMAND", addr)

def server_loop():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server_sock:
        server_sock.bind((SERVER_IP, SERVER_PORT))
        print(f"[✓] Server running on {SERVER_IP}:{SERVER_PORT}")
        while True:
            try:
                data, addr = server_sock.recvfrom(1024)
                threading.Thread(target=handle_request, args=(data, addr, server_sock), daemon=True).start()
            except Exception as e:
                print(f"[!] Error: {e}")

if __name__ == "__main__":
    server_loop()

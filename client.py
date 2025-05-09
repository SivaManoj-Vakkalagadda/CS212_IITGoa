import socket
import pyaudio
import threading
import numpy as np
import noisereduce as nr
import time
import uuid
import os

# Audio Config
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
VOIP_PORT = 5150
CHAT_PORT = 5050  # New TCP port for full-duplex chat
SERVER_PORT = 9999
BUFFER_SIZE = 2048
HANDSHAKE_MSG = b"HANDSHAKE"

# File Transfer Config
FILE_PORT = 50009
CHUNK_SIZE = 1024
EOF = b"*EOF*"

# Utility functions
def get_mac_address():
    mac = uuid.getnode()
    return ':'.join([f'{(mac >> ele) & 0xff:02X}' for ele in range(40, -1, -8)])

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    finally:
        s.close()
    return ip

def register_with_server(server_ip):
    mac = get_mac_address()
    msg = f"REGISTER,{mac}"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(msg.encode(), (server_ip, SERVER_PORT))
        resp, _ = s.recvfrom(1024)
        decoded = resp.decode()
        if decoded.startswith("REGISTERED"):
            number = decoded.split(',')[1]
            print(f"[✓] Registered successfully. Your peer number is {number}")
            return True
        elif decoded == "NO_NUMBERS_LEFT":
            print("[✗] Server can't register new users. No numbers left.")
        else:
            print("[✗] Registration failed.")
        return False

def get_ip_from_number(server_ip, number):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        msg = f"GET,{number}"
        s.sendto(msg.encode(), (server_ip, SERVER_PORT))
        try:
            s.settimeout(5)
            data, _ = s.recvfrom(1024)
            if data == b"NOT_FOUND":
                return None
            return data.decode().split(',')[1]
        except socket.timeout:
            return None

def get_number_from_ip(server_ip, ip):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        msg = f"WHO,{ip}"
        s.sendto(msg.encode(), (server_ip, SERVER_PORT))
        try:
            s.settimeout(5)
            data, _ = s.recvfrom(1024)
            if data == b"NOT_FOUND":
                return None
            return data.decode().split(',')[1]
        except socket.timeout:
            return None

# Audio Communication
def audio_stream(is_caller, peer_ip=None, server_ip=None):
    p = pyaudio.PyAudio()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2)
    stop_event = threading.Event()
    target_addr = None

    if not is_caller:
        sock.bind(('', VOIP_PORT))
        print("[✓] Waiting for incoming call...")
        start_time = time.time()
        while time.time() - start_time < 15:
            try:
                data, addr = sock.recvfrom(BUFFER_SIZE)
                if data == HANDSHAKE_MSG:
                    caller_number = get_number_from_ip(server_ip, addr[0])
                    print(f"[✓] Call from {caller_number if caller_number else addr[0]}")
                    response = input("[?] Accept? (y/n): ").strip().lower()
                    if response == 'y':
                        target_addr = addr
                        sock.sendto(b"ACCEPT", target_addr)
                        break
                    else:
                        sock.sendto(b"DECLINE", addr)
                        return
            except socket.timeout:
                continue
        else:
            print("[✗] No incoming call within 15 seconds.")
            return
    else:
        target_addr = (peer_ip, VOIP_PORT)
        print("[•] Sending call request...")
        start_time = time.time()
        accepted = False
        while time.time() - start_time < 15:
            sock.sendto(HANDSHAKE_MSG, target_addr)
            try:
                data, _ = sock.recvfrom(BUFFER_SIZE)
                if data == b"ACCEPT":
                    accepted = True
                    break
                elif data == b"DECLINE":
                    print("[✗] Call declined.")
                    return
            except socket.timeout:
                time.sleep(0.5)
        if not accepted:
            print("[✗] No response to call within 15 seconds.")
            return

    stream_out = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, output=True, frames_per_buffer=CHUNK)
    stream_in = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)

    def receive():
        while not stop_event.is_set():
            try:
                data, _ = sock.recvfrom(BUFFER_SIZE)
                stream_out.write(data)
            except:
                break

    def send():
        while not stop_event.is_set():
            try:
                data = stream_in.read(CHUNK, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.int16)
                reduced = nr.reduce_noise(y=audio_data, sr=RATE)
                sock.sendto(reduced.astype(np.int16).tobytes(), target_addr)
            except:
                break

    threading.Thread(target=receive, daemon=True).start()
    threading.Thread(target=send, daemon=True).start()

    while not stop_event.is_set():
        if input().strip().upper() == "END_VOICE":
            stop_event.set()

    stream_in.stop_stream()
    stream_out.stop_stream()
    stream_in.close()
    stream_out.close()
    sock.close()
    p.terminate()

# File Transfer
def file_transfer(mode, peer_ip=None, server_ip=None):
    if mode == "send":
        filename = input("Enter filename: ").strip()
        if not os.path.exists(filename):
            print("[✗] File not found.")
            return
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.connect((peer_ip, FILE_PORT))
                sock.settimeout(15)
                sock.send(filename.encode())
                print("[•] Waiting for file transfer acceptance...")
                ack = sock.recv(1024)
                if ack != b"ACCEPT":
                    print("[✗] File transfer declined.")
                    return
                with open(filename, "rb") as f:
                    while chunk := f.read(CHUNK_SIZE):
                        sock.send(chunk)
                    sock.send(EOF)
                print("[✓] File sent.")
            except Exception as e:
                print("[✗] Failed:", e)
    elif mode == "receive":
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(('0.0.0.0', FILE_PORT))
            sock.listen(1)
            sock.settimeout(15)
            print("[✓] Waiting for file transfer...")
            try:
                conn, addr = sock.accept()
            except socket.timeout:
                print("[✗] No file received in 15 seconds. Returning to chat.")
                return
            with conn:
                filename = conn.recv(CHUNK_SIZE).decode().strip()
                peer_number = get_number_from_ip(server_ip, addr[0])
                display_name = peer_number if peer_number else addr[0]
                response = input(f"[?] Accept file '{filename}' from {display_name}? (y/n): ").strip().lower()
                if response != 'y':
                    conn.send(b"DECLINE")
                    print("[✗] File transfer declined.")
                    return
                conn.send(b"ACCEPT")
                with open(filename, "wb") as f:
                    while True:
                        chunk = conn.recv(CHUNK_SIZE)
                        if EOF in chunk:
                            f.write(chunk.replace(EOF, b""))
                            break
                        f.write(chunk)
                print(f"[✓] Received: {filename}")

# TCP Chat
def tcp_chat(sock, peer_ip, my_number, server_ip):
    stop_event = threading.Event()
    peer_number = get_number_from_ip(server_ip, peer_ip) or peer_ip

    def receiver():
        while not stop_event.is_set():
            try:
                data = sock.recv(1024).decode()
                if not data:
                    print("[✗] Disconnected by peer.")
                    stop_event.set()
                    break
                print(f"\n[{peer_number}] {data}")
            except:
                break

    def sender():
        while not stop_event.is_set():
            try:
                msg = input("You: ").strip()
                if msg == "USE_FEATURE":
                    feature = input("Enter feature (voip/file): ").strip().lower()
                    if feature == "voip":
                        role = input("Call or receive? ").strip().lower()
                        if role == "call":
                            audio_stream(True, peer_ip, server_ip)
                        elif role == "receive":
                            audio_stream(False, server_ip=server_ip)
                    elif feature == "file":
                        role = input("Send or receive? ").strip().lower()
                        file_transfer(role, peer_ip, server_ip)
                elif msg == "END_CONNECTION":
                    sock.sendall(msg.encode())
                    stop_event.set()
                else:
                    sock.sendall(msg.encode())
            except:
                break

    threading.Thread(target=receiver, daemon=True).start()
    sender()
    sock.close()

# Entry Point
def main():
    server_ip = input("Enter Server IP: ").strip()
    if not register_with_server(server_ip):
        print("[✗] Registration failed.")
        return

    my_ip = get_local_ip()
    my_number = get_number_from_ip(server_ip, my_ip)
    if not my_number:
        print("[✗] Could not fetch your number.")
        return

    while True:
        mode = input("connect / receive / exit: ").strip().lower()
        if mode == "connect":
            try:
                number = int(input("Enter peer number: "))
            except ValueError:
                continue
            peer_ip = get_ip_from_number(server_ip, number)
            if peer_ip:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(15)
                    sock.connect((peer_ip, CHAT_PORT))
                    sock.sendall(f"CONNECT_REQUEST,{my_number}".encode())
                    response = sock.recv(1024).decode()
                    if response != "ACCEPT":
                        print("[✗] Connection declined.")
                        sock.close()
                        continue
                    print(f"[✓] Connected to {number}")
                    tcp_chat(sock, peer_ip, my_number, server_ip)
                except Exception as e:
                    print(f"[✗] Connection error: {e}")
            else:
                print("[✗] Number not found.")
        elif mode == "receive":
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(('', CHAT_PORT))
            sock.listen(1)
            sock.settimeout(15)
            print("[✓] Waiting for connection...")
            try:
                conn, addr = sock.accept()
                data = conn.recv(1024).decode()
                if data.startswith("CONNECT_REQUEST"):
                    peer_number = data.split(',')[1]
                    print(f"[✓] Chat request from {peer_number}")
                    response = input("[?] Accept chat? (y/n): ").strip().lower()
                    if response == 'y':
                        conn.sendall(b"ACCEPT")
                        tcp_chat(conn, addr[0], my_number, server_ip)
                    else:
                        conn.sendall(b"DECLINE")
                        conn.close()
            except socket.timeout:
                print("[✗] No incoming connection within 15 seconds.")
                continue
        elif mode == "exit":
            break
        else:
            print("[✗] Invalid choice.")

if __name__ == "__main__":
    main()



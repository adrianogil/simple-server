import requests
import uuid
import os


def send_file_to_server(file_path, url):
    with open(file_path, "rb") as f:
        file_data = f.read()
        
    boundary = str(uuid.uuid4())
    headers = {'Content-Type': f'multipart/form-data; boundary={boundary}'}
    
    data = f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{os.path.basename(file_path)}\"\r\nContent-Type: application/octet-stream\r\n\r\n{file_data.decode()}\r\n--{boundary}--\r\n"
    response = requests.post(url, headers=headers, data=data.encode())
    
    if response.status_code == 200:
        print("File sent successfully to the server")
    else:
        print("Failed to send the file to the server")


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        file_path = input("Enter the path of the file: ")
    else:
        file_path = sys.argv[1]
    if len(sys.argv) < 3:
        url = input("Enter the URL of the server: ")
    else:
        url = sys.argv[2]

    if os.path.isdir(file_path):
        for root, dirs, files in os.walk(file_path):
            for file in files:
                file_path = os.path.join(root, file)
                print(f"Sending file: {file_path}")
                send_file_to_server(file_path, url)
    else:
        send_file_to_server(file_path, url)

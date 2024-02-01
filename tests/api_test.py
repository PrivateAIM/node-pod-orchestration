import requests

# Assuming you have obtained the external IP address or hostname of your service
service_url = "https://192.168.49.2:32367/service"

# Send GET request to the service endpoint
response = requests.get(service_url)

# Check the response
if response.status_code == 200:
    print("Service endpoint responded with:", response.text)
else:
    print("Error:", response.status_code)

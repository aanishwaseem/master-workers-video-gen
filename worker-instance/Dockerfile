# Use an official Python runtime as a parent image (matching the compiled cpython-313)
FROM python:3.13-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the current directory contents into the container at /app
COPY . .

# Run bootstrapper.py when the container launches (update this if a different script should be the entry point)
CMD ["python", "bootstrapper.py"]

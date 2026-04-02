# 1. Corrected Python base
FROM python:3.10

# 2. Install SSH and dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server \
    && rm -rf /var/lib/apt/lists/*

# 3. Configure SSH for root login (Fixed mkdir with -p)
RUN mkdir -p /var/run/sshd && \
    mkdir -p /root/.ssh && \
    sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config && \
    sed -i 's@session\s*required\s*pam_loginuid.so@session optional pam_loginuid.so@g' /etc/pam.d/sshd

# 4. Set the working directory
WORKDIR /app

# 5. Application dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copy your code
COPY . .

# 7. Expose Port 22
EXPOSE 22

# 8. Optimized CMD for Vast.ai (Injects key if provided, starts SSH, then runs app)
CMD if [ -n "$SSH_PUBLIC_KEY" ]; then echo "$SSH_PUBLIC_KEY" >> /root/.ssh/authorized_keys; fi && \
    service ssh start && \
    python bootstrapper.py
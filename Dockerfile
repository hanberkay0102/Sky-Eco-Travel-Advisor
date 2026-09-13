# ══════════════════════════════════════════════════════════════
# Dockerfile — Rasa Server for Sky Eco-Travel Advisor
# ══════════════════════════════════════════════════════════════
# This container runs the Rasa server that handles NLU
# (understanding user messages) and dialogue management
# (deciding what to say next). It loads the trained model
# and exposes the REST + Socket.IO channels on port 5005.
# ══════════════════════════════════════════════════════════════

FROM rasa/rasa:3.6.21-full

# Switch to root to install dependencies and copy files
USER root

# Copy the trained model into the container
# The model file is a .tar.gz archive produced by "rasa train"
COPY ./models/ /app/models/

# Copy Rasa configuration files
COPY ./config.yml     /app/config.yml
COPY ./domain.yml     /app/domain.yml
COPY ./credentials.yml /app/credentials.yml
COPY ./endpoints.yml  /app/endpoints.yml
COPY ./data/          /app/data/

# Switch back to the non-root user for security
USER 1001

# Expose the default Rasa server port
EXPOSE 5005

# Start Rasa server with API and CORS enabled
# --enable-api: allows REST API access for the frontend
# --cors "*":   allows requests from any origin (needed for
#               the frontend served on a different port)
CMD ["run", "--enable-api", "--cors", "*", "--port", "5005"]

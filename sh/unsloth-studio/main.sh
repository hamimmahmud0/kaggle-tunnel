# 0. Install utilities
#

apt update && apt install tmux btop

# 1. Install uv non-interactively
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# 2. Create and activate a virtual environment
uv venv unsloth_env --python 3.12
source unsloth_env/bin/activate

# 3. Install Unsloth non-interactively
uv pip install unsloth --torch-backend=auto

# 1. Clone the Unsloth repository
git clone https://github.com/unslothai/unsloth.git
cd unsloth

# 2. Run the local installer non-interactively
# (This builds the UI backend and places environment markers where the CLI expects them)
./install.sh --local


# 3. Setup cloudflared tunnel

# Add cloudflare gpg key
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null

# Add this repo to your apt repositories
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' | sudo tee /etc/apt/sources.list.d/cloudflared.list

# install cloudflared
sudo apt-get update && sudo apt-get install cloudflared

# 4. Run tunnel
## Public Tunnel
# tmux new-session -d -s tunnel "cloudflared tunnel --url http://localhost:8888"

## Private Tunnel
tmux new-session -d -s tunnel "sudo cloudflared service install eyJhIjoiNjFkN2Y2ODM3Nzg4N2YxYzZjMWU1YjNiY2YxODNlZjAiLCJ0IjoiYWMzMjYyODQtNzMzMC00YjE1LTkyMjYtNWUwNDk2NjM1NGFhIiwicyI6Ik1qRmtaREZsWVdRdFlXSmxNeTAwWWpoaUxXSmhOell0TldRM05USTBNRFl3T1RoaiJ9"

# 5. Launch the Studio server
tmux new-session -d -s unsloth_server "export MPLBACKEND=Agg && unsloth studio -H 0.0.0.0 -p 8888"


# 6. Launch btop
tmux new-session -d -s btop "btop"

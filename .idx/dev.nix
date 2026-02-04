# To learn more about how to use Nix to configure your environment
# see: https://developers.google.com/idx/guides/customize-idx-env
{ pkgs, ... }: {
  # Which nixpkgs channel to use.
  channel = "stable-24.05"; # or "unstable"
  # Use https://search.nixos.org/packages to find packages
  packages = [
    pkgs.python311
    pkgs.python311Packages.pip
    pkgs.playwright-driver # Helps with playwright dependencies
  ];
  # Sets environment variables in the workspace
  env = {
    PLAYWRIGHT_BROWSERS_PATH = "$HOME/playwright-browsers";
  };
  idx = {
    # Search for the extensions you want on https://open-vsx.org/ and use "publisher.id"
    extensions = [
      "ms-python.python"
      "google.gemini-cli-vscode-ide-companion"
    ];
    # Enable previews
    previews = {
      enable = true;
      previews = {
        web = {
          command = ["streamlit" "run" "Frontend/app.py" "--server.port" "$PORT" "--server.headless" "true"];
          manager = "web";
        };
      };
    };
    # Workspace lifecycle hooks
    workspace = {
      # Runs when a workspace is first created
      onCreate = {
        setup-envs = ''
          python3 -m venv .venv
          source .venv/bin/activate
          pip install -r Backend/requirements.txt
          pip install -r Frontend/requirements.txt
          playwright install chromium
        '';
        default.openFiles = [ "README.md" "Frontend/app.py" "Backend/main.py" ];
      };
      # Runs when the workspace is (re)started
      onStart = {
        # We can't easily run two blocking processes in onStart for the preview, 
        # but the user has a run_app.py script.
        # We'll set up the environment so they can just run it.
        # Alternatively, we could start the backend in background.
        start-backend = ''
          source .venv/bin/activate
          # Run backend in background for the preview to work with it? 
          # Or just let the user run run_app.py. 
          # The preview command above only runs streamlit.
          # Let's try to make the preview command run both or just rely on manual run.
          # For now, just ensure venv is activated in terminals if possible, but nix shell handles paths.
        '';
      };
    };
  };
}

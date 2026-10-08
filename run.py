import sys
from app import create_app
from app.config import Config

if __name__ == "__main__":
    config = Config()
    # Enforce local only requirement
    host = "127.0.0.1"
    port = config.PORT

    print(f"Starting CraftersMC Bazaar Flip Dashboard on http://{host}:{port} ...")
    app = create_app(config_override=config, start_refresher=True)

    try:
        app.run(host=host, port=port, debug=config.DEBUG, use_reloader=False)
    except (KeyboardInterrupt, SystemExit):
        refresher = app.extensions.get("bazaar_refresher")
        if refresher:
            refresher.stop()
        sys.exit(0)

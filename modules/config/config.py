from pathlib import Path
import json

default_config = {
    "input_path": str(Path.home() / "cully" / "input"),
    "output_path": str(Path.home() / "cully" / "output"),
}


class Config:
    config_path: Path
    input_path: str
    output_path: str

    def __init__(self):
        self.config_path = Path.home() / ".config" / "cully" / "config.json"
        self.input_path = self._load_config("input_path")
        self.output_path = self._load_config("output_path")
        print(self.input_path)

    def _load_config(self, config: str):
        """Retrieves config.json in .config and loads the settings
        Args:
            config (str): The name of the setting to retrieve.
        Returns:
            The value of the setting if found, otherwise what is set in default.
        """
        config_path = Path.home() / ".config" / "cully" / "config.json"
        Path(config_path.parent).mkdir(
            parents=True, exist_ok=True
        )  # Ensure the directory exists

        if config_path.exists():
            with open(config_path, "r") as f:
                config_file = json.load(f)

                # If file exist but setting does not
                if config_file.get(config) is None:
                    config_file[config] = default_config.get(config)
                    with open(config_path, "w") as f_write:
                        json.dump(config_file, f_write, indent=4)
                return config_file.get(config)
        else:
            with open(config_path, "w") as f:
                json.dump(default_config, f, indent=4)
            with open(config_path, "r") as f:
                config_file = json.load(f)
                return config_file.get(config)

    """update_config
        args:
            config = config variable wanting to change
            value = new value for that variable
        returns:
            None
            
    """

    def update_cofig(self, config, value):
        config_path = Path.home() / ".config" / "cully" / "config.json"
        # Create directory if config director doesn't exists
        Path(config_path.parent).mkdir(parents=True, exist_ok=True)
        if config_path.exists():
            with open(config_path, "r") as f:
                config_file = json.load(f)
                config_file[config] = value
            with open(config_path, "w") as f:
                json.dump(config_file, f, indent=4)

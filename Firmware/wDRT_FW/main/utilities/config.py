import json
import uos as os
from time import ticks_us

class Configurator:
    """
    Class to manage configuration settings.
    This class handles the loading, updating, and saving of configuration settings stored in a JSON file.
    """
    def __init__(self, fname, debug=False):
        """
        Initializes the Configurator with a specified configuration file.

        Args:
            fname (str): The name of the configuration file.
            debug (bool): If True, debug information is printed. Defaults to False.
        """
        self._debug = debug
        if self._debug: print(f'{ticks_us()} Configurator.__init__')
        
        self._fname = fname
        self.config = self._load()

    def get_config_str(self):
        """
        Returns the configuration settings as a string.

        Returns:
            str: The configuration settings in key-value format separated by commas.
        """
        if self._debug: print(f'{ticks_us()} Configurator.get_config_str')
        
        cnf = ""
        for i in self.config:
            cnf += "{}:{},".format(i, self.config[i])
        return cnf[:-1]

    def update(self, cfgs):
        """
        Updates the configuration settings.

        Args:
            cfgs (str or dict): A string or dictionary containing the new configuration settings.
        """
        # if self._debug:
        print(f'{ticks_us()} Configurator.update got:{cfgs}')
        
        if isinstance(cfgs, str):
            try:
                c = cfgs.split(",")
                for cnf in c:
                    kv = cnf.split(':')
                    self.config.update({kv[0]: kv[1]})
            except:
                print("Error: Invalid configuration string.")
        elif isinstance(cfgs, dict):
            self.config = cfgs
        else:
            print("Error: Invalid input for updating configuration.")
        self._save()

    def _load(self):
        """
        Loads the configuration settings from the specified file.

        Returns:
            dict: A dictionary containing the configuration settings.
        """
        if self._debug: print(f'{ticks_us()} Configurator._load')
        
        if os.stat(self._fname):
            with open(self._fname, 'r') as infile:
                try:
                    return json.loads(infile.read())
                except ValueError:
                    print("Error: Configuration file contains invalid JSON.")
                    return dict()
        else:
            with open(self._fname, 'w') as infile:
                return dict()

    def _save(self):
        """
        Saves the current configuration settings to the specified file.
        """
        if self._debug: print(f'{ticks_us()} Configurator._save')
        
        with open(self._fname, 'w') as outfile:
            outfile.write(json.dumps(self.config))

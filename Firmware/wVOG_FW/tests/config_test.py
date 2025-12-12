import os
import json
import uasyncio as asyncio

from wVOG.config import Configurator


class ConfiguratorTest:
    def __init__(self):
        self.sample_config = {
            "setting1": "value1",
            "setting2": "value2",
            "setting3": "value3"
        }

    async def run_test(self):
        self._test_configurator()
        print("Configurator test passed.")

    def _test_configurator(self):
        # Create a sample JSON configuration file
        with open('test_config.json', 'w') as f:
            json.dump(self.sample_config, f)

        # Create a new Configurator object
        config = Configurator('test_config.json')

        # Test the get_config_str() method
        config_str = config.get_config_str()
        config_dict = dict(kv.split(':') for kv in config_str.split(','))

        for key, value in self.sample_config.items():
            assert key in config_dict
            assert config_dict[key] == value

        # Test the update() method with a dictionary
        new_settings = {"setting4": "value4", "setting5": "value5"}
        config.update(new_settings)
        updated_config = config.config
        assert updated_config["setting4"] == "value4"
        assert updated_config["setting5"] == "value5"

        # Test the update() method with a string
        config.update("setting6:value6,setting7:value7")
        updated_config = config.config
        assert updated_config["setting6"] == "value6"
        assert updated_config["setting7"] == "value7"

        # Cleanup
        os.remove('test_config.json')


if __name__ == "__main__":
    async def main():
        configurator_test = ConfiguratorTest()
        await configurator_test.run_test()

    asyncio.run(main())
from uasyncio import run 
from tests import switch_test, lens_test, xb_test, config_test, lipo_test, mmc_test, timers_test 

if __name__ == "__main__":
    run(switch_test.SwitchTest().run_test())
    run(lens_test.LensTest(verbose = True).run_test(repeats=2))
    run(xb_test.XbTest().run_test(repeats=2))
    run(config_test.ConfiguratorTest().run_test())
    run(lipo_test.LipoReaderTest().run_test(repeats=2))
    run(mmc_test.MMCWriteTest().run_test())
    run(timers_test.TimerTest().run_test())
    

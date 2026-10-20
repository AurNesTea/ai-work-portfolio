from aiwork.triggers.cron_run import main


def test_cron_main_requires_workflow():
    assert main([]) == 2

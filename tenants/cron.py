# tenants/cron.py
from django_cron import CronJobBase, Schedule
from tenants.management.commands.check_subscription_expiry import Command

class CheckSubscriptionExpiryCronJob(CronJobBase):
    RUN_EVERY_MINS = 1440  # Run every 24 hours (1440 minutes)
    
    schedule = Schedule(run_every_mins=RUN_EVERY_MINS)
    code = 'tenants.check_subscription_expiry'
    
    def do(self):
        Command().handle()
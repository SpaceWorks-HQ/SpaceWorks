"""Deployment fan-out; the service owns one source-gate boundary per tenant."""

from celery import shared_task

from apps.devices.services_offline import scan_offline_devices


@shared_task
def scan_offline_devices_task():
    return scan_offline_devices()

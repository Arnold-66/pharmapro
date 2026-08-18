# inventory/templatetags/inventory_filters.py - Create this file

from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary using a key"""
    return dictionary.get(key, [])


@register.filter
def multiply(value, arg):
    """Multiply the value by arg"""
    try:
        return value * arg
    except (TypeError, ValueError):
        return 0

@register.filter
def subtract(value, arg):
    """Subtract arg from value"""
    try:
        return value - arg
    except (TypeError, ValueError):
        return 0

@register.filter
def divide(value, arg):
    """Divide value by arg"""
    try:
        if arg == 0:
            return 0
        return value / arg
    except (TypeError, ValueError):
        return 0

@register.filter
def currency(value):
    """Format value as currency"""
    try:
        return f"Ugx {value:,.0f}"
    except (TypeError, ValueError):
        return "Ugx 0"
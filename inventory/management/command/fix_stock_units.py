from django.core.management.base import BaseCommand
from apps.inventory.models import Product, SaleUnit

class Command(BaseCommand):
    help = 'Fix stock units for existing products'

    def handle(self, *args, **options):
        products = Product.objects.all()
        
        for product in products:
            self.stdout.write(f'Processing: {product.name}')
            
            # Check if product has sale units
            if not product.sale_units.exists():
                # Create default sale unit based on product's unit
                SaleUnit.objects.create(
                    tenant=product.tenant,
                    product=product,
                    name=product.unit.name if product.unit else 'Unit',
                    abbreviation=product.unit.abbreviation if product.unit else 'U',
                    quantity_per_unit=1,
                    selling_price=product.selling_price,
                    purchase_price=product.purchase_price,
                    is_default=True,
                    is_active=True
                )
                self.stdout.write(f'  - Created default sale unit for {product.name}')
            
            # Check if allow_fractional is set
            if not hasattr(product, 'allow_fractional'):
                product.allow_fractional = False
                product.save()
                self.stdout.write(f'  - Added allow_fractional field to {product.name}')
        
        self.stdout.write(self.style.SUCCESS('Successfully fixed stock units for all products'))
# apps/sales/serializers.py
from rest_framework import serializers
from django.db.models import Sum, Q
from django.utils import timezone
from .models import Customer, Sale, SaleItem, Payment
from inventory.models import Product, StockMovement
from inventory.serializers import ProductListSerializer

class CustomerSerializer(serializers.ModelSerializer):
    """Customer serializer"""
    total_purchases = serializers.SerializerMethodField()
    last_purchase_date = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Customer
        fields = [
            'id', 'tenant', 'name', 'email', 'phone', 'address',
            'type', 'tax_id', 'credit_limit', 'balance',
            'notes', 'is_active',
            'total_purchases', 'last_purchase_date',
            'created_by', 'created_by_name',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'tenant', 'created_by', 'created_at', 'updated_at'
        ]
    
    def get_total_purchases(self, obj):
        total = obj.sales.aggregate(
            total=Sum('total_amount')
        )['total']
        return total or 0
    
    def get_last_purchase_date(self, obj):
        last_sale = obj.sales.order_by('-sale_date').first()
        return last_sale.sale_date if last_sale else None
    
    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() if obj.created_by else None
    
    def validate_email(self, value):
        """Validate email is unique for tenant"""
        tenant = self.context.get('tenant') or self.instance.tenant if self.instance else None
        if tenant and Customer.objects.filter(tenant=tenant, email=value).exclude(id=self.instance.id if self.instance else None).exists():
            raise serializers.ValidationError("A customer with this email already exists.")
        return value


class SaleItemSerializer(serializers.ModelSerializer):
    """Sale item serializer"""
    product_name = serializers.SerializerMethodField()
    product_sku = serializers.SerializerMethodField()
    product_details = ProductListSerializer(source='product', read_only=True)
    
    class Meta:
        model = SaleItem
        fields = [
            'id', 'sale', 'product', 'product_name', 'product_sku',
            'product_details', 'quantity', 'unit_price',
            'total_price', 'discount', 'tax', 'notes',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']
    
    def get_product_name(self, obj):
        return obj.product.name if obj.product else None
    
    def get_product_sku(self, obj):
        return obj.product.sku if obj.product else None
    
    def validate(self, data):
        """Validate sale item"""
        product = data.get('product')
        quantity = data.get('quantity', 0)
        unit_price = data.get('unit_price', 0)
        
        if not product:
            raise serializers.ValidationError("Product is required.")
        
        # Check stock availability
        if quantity > product.quantity:
            raise serializers.ValidationError({
                "quantity": f"Insufficient stock. Available: {product.quantity}"
            })
        
        if quantity <= 0:
            raise serializers.ValidationError({
                "quantity": "Quantity must be greater than zero."
            })
        
        if unit_price < 0:
            raise serializers.ValidationError({
                "unit_price": "Unit price cannot be negative."
            })
        
        # Calculate total price
        data['total_price'] = quantity * unit_price
        
        return data


class PaymentSerializer(serializers.ModelSerializer):
    """Payment serializer"""
    created_by_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Payment
        fields = [
            'id', 'tenant', 'sale', 'amount', 'method',
            'reference', 'notes', 'created_by', 'created_by_name',
            'created_at'
        ]
        read_only_fields = ['id', 'tenant', 'created_by', 'created_at']
    
    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() if obj.created_by else None


class SaleSerializer(serializers.ModelSerializer):
    """Sale serializer with full details"""
    items = SaleItemSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    customer_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    total_paid = serializers.SerializerMethodField()
    status_badge = serializers.SerializerMethodField()
    
    class Meta:
        model = Sale
        fields = [
            'id', 'tenant', 'invoice_number', 'customer',
            'customer_name', 'sale_date', 'due_date',
            'subtotal', 'tax_amount', 'discount_amount',
            'shipping_cost', 'total_amount', 'paid_amount',
            'balance_due', 'payment_status', 'payment_method',
            'payment_date', 'shipping_address',
            'delivery_status', 'tracking_number',
            'notes', 'internal_notes',
            'items', 'payments', 'total_paid',
            'status_badge',
            'created_by', 'created_by_name',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'tenant', 'invoice_number', 'created_by',
            'created_at', 'updated_at'
        ]
    
    def get_customer_name(self, obj):
        return obj.customer.name if obj.customer else None
    
    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() if obj.created_by else None
    
    def get_total_paid(self, obj):
        return obj.payments.aggregate(total=Sum('amount'))['total'] or 0
    
    def get_status_badge(self, obj):
        """Get status badge CSS class"""
        status_colors = {
            'paid': 'success',
            'partial': 'warning',
            'unpaid': 'danger',
            'refunded': 'secondary',
        }
        return status_colors.get(obj.payment_status, 'secondary')
    
    def validate(self, data):
        """Validate sale data"""
        due_date = data.get('due_date')
        if due_date and due_date < timezone.now().date():
            raise serializers.ValidationError({
                "due_date": "Due date cannot be in the past."
            })
        
        return data


class SaleCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating sales with items"""
    items = SaleItemSerializer(many=True, required=True)
    
    class Meta:
        model = Sale
        fields = [
            'customer', 'due_date', 'payment_method',
            'shipping_address', 'delivery_status',
            'notes', 'internal_notes', 'items'
        ]
    
    def validate_items(self, value):
        """Validate items list"""
        if not value:
            raise serializers.ValidationError("At least one item is required.")
        
        # Check for duplicate products
        products = [item.get('product') for item in value]
        if len(products) != len(set(products)):
            raise serializers.ValidationError("Duplicate products found in items.")
        
        return value
    
    def validate(self, data):
        """Validate sale data"""
        # Check all items have stock
        for item_data in data.get('items', []):
            product = item_data.get('product')
            quantity = item_data.get('quantity', 0)
            if quantity > product.quantity:
                raise serializers.ValidationError({
                    "items": f"Insufficient stock for {product.name}. Available: {product.quantity}"
                })
        
        return data
    
    def create(self, validated_data):
        """Create sale with items and update stock"""
        items_data = validated_data.pop('items')
        tenant = self.context.get('tenant')
        request = self.context.get('request')
        
        # Generate invoice number
        sale_count = Sale.objects.filter(tenant=tenant).count() + 1
        invoice_number = f"INV-{timezone.now().year}{sale_count:06d}"
        
        # Calculate totals
        subtotal = 0
        for item_data in items_data:
            product = item_data.get('product')
            quantity = item_data.get('quantity')
            unit_price = item_data.get('unit_price')
            total_price = quantity * unit_price
            subtotal += total_price
            
            # Update product stock
            product.quantity -= quantity
            product.save(update_fields=['quantity', 'updated_at'])
            
            # Create stock movement
            StockMovement.objects.create(
                tenant=tenant,
                product=product,
                movement_type='sale',
                quantity=quantity,
                previous_quantity=product.quantity + quantity,
                new_quantity=product.quantity,
                unit_price=unit_price,
                total_price=total_price,
                reference=invoice_number,
                created_by=request.user if request else None
            )
        
        # Create sale
        sale = Sale.objects.create(
            tenant=tenant,
            invoice_number=invoice_number,
            subtotal=subtotal,
            total_amount=subtotal,
            created_by=request.user if request else None,
            **validated_data
        )
        
        # Create sale items
        for item_data in items_data:
            SaleItem.objects.create(
                sale=sale,
                total_price=item_data.get('quantity') * item_data.get('unit_price'),
                **item_data
            )
        
        # Update customer balance
        customer = sale.customer
        customer.balance += sale.total_amount
        customer.save(update_fields=['balance'])
        
        return sale
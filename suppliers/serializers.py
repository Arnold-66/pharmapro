# apps/suppliers/serializers.py
from rest_framework import serializers
from django.db.models import Sum, Q
from .models import Supplier, SupplierProduct, PurchaseOrder, PurchaseOrderItem
from inventory.models import Product
from inventory.serializers import ProductListSerializer
from django.utils import timezone

class SupplierSerializer(serializers.ModelSerializer):
    """Supplier serializer"""
    product_count = serializers.SerializerMethodField()
    purchase_order_count = serializers.SerializerMethodField()
    total_purchases = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    performance_rating = serializers.SerializerMethodField()
    
    class Meta:
        model = Supplier
        fields = [
            'id', 'tenant', 'name', 'code', 'contact_person',
            'email', 'phone', 'alternative_phone',
            'address', 'city', 'state', 'country', 'postal_code',
            'tax_id', 'registration_number', 'website',
            'payment_terms', 'payment_method', 'credit_limit',
            'balance_due', 'lead_time_days', 'quality_rating',
            'reliability_score', 'performance_rating',
            'status', 'is_approved', 'notes',
            'product_count', 'purchase_order_count', 'total_purchases',
            'created_by', 'created_by_name',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'tenant', 'created_by', 'created_at', 'updated_at'
        ]
    
    def get_product_count(self, obj):
        return obj.products.count()
    
    def get_purchase_order_count(self, obj):
        return obj.purchase_orders.count()
    
    def get_total_purchases(self, obj):
        total = obj.purchase_orders.aggregate(
            total=Sum('total_amount')
        )['total']
        return total or 0
    
    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() if obj.created_by else None
    
    def get_performance_rating(self, obj):
        """Calculate performance rating based on quality and reliability"""
        avg_rating = (obj.quality_rating + obj.reliability_score) / 2
        return round(avg_rating, 1)
    
    def validate_code(self, value):
        """Validate supplier code is unique for tenant"""
        tenant = self.context.get('tenant') or self.instance.tenant if self.instance else None
        if tenant and Supplier.objects.filter(tenant=tenant, code=value).exclude(id=self.instance.id if self.instance else None).exists():
            raise serializers.ValidationError("A supplier with this code already exists.")
        return value
    
    def validate_email(self, value):
        """Validate email format"""
        from django.core.validators import validate_email
        try:
            validate_email(value)
        except:
            raise serializers.ValidationError("Invalid email format.")
        return value


class SupplierProductSerializer(serializers.ModelSerializer):
    """Supplier product serializer"""
    product_details = ProductListSerializer(source='product', read_only=True)
    supplier_name = serializers.SerializerMethodField()
    
    class Meta:
        model = SupplierProduct
        fields = [
            'id', 'tenant', 'supplier', 'supplier_name',
            'product', 'product_details',
            'supplier_product_code', 'supplier_product_name',
            'purchase_price', 'lead_time_days',
            'minimum_order_quantity', 'is_preferred',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'tenant', 'created_at', 'updated_at']
    
    def get_supplier_name(self, obj):
        return obj.supplier.name if obj.supplier else None
    
    def validate(self, data):
        """Validate supplier product relationship"""
        supplier = data.get('supplier')
        product = data.get('product')
        
        if supplier and product:
            # Check if relationship already exists
            if SupplierProduct.objects.filter(
                supplier=supplier, 
                product=product
            ).exclude(id=self.instance.id if self.instance else None).exists():
                raise serializers.ValidationError(
                    "This product is already associated with this supplier."
                )
        
        return data


class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    """Purchase order item serializer"""
    product_name = serializers.SerializerMethodField()
    product_sku = serializers.SerializerMethodField()
    
    class Meta:
        model = PurchaseOrderItem
        fields = [
            'id', 'purchase_order', 'product', 'product_name',
            'product_sku', 'quantity', 'unit_price',
            'total_price', 'received_quantity', 'notes',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_product_name(self, obj):
        return obj.product.name if obj.product else None
    
    def get_product_sku(self, obj):
        return obj.product.sku if obj.product else None
    
    def validate(self, data):
        """Validate purchase order item"""
        quantity = data.get('quantity', 0)
        unit_price = data.get('unit_price', 0)
        
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


class PurchaseOrderSerializer(serializers.ModelSerializer):
    """Purchase order serializer"""
    items = PurchaseOrderItemSerializer(many=True, read_only=True)
    supplier_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    total_items = serializers.SerializerMethodField()
    received_percentage = serializers.SerializerMethodField()
    
    class Meta:
        model = PurchaseOrder
        fields = [
            'id', 'tenant', 'po_number', 'supplier', 'supplier_name',
            'status', 'order_date', 'expected_delivery_date',
            'actual_delivery_date', 'subtotal', 'tax_amount',
            'discount_amount', 'shipping_cost', 'total_amount',
            'notes', 'internal_notes',
            'approved_by', 'approved_by_name', 'approved_at',
            'items', 'total_items', 'received_percentage',
            'created_by', 'created_by_name',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'tenant', 'po_number', 'created_by',
            'created_at', 'updated_at'
        ]
    
    def get_supplier_name(self, obj):
        return obj.supplier.name if obj.supplier else None
    
    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() if obj.created_by else None
    
    def get_approved_by_name(self, obj):
        return obj.approved_by.get_full_name() if obj.approved_by else None
    
    def get_total_items(self, obj):
        return obj.items.count()
    
    def get_received_percentage(self, obj):
        """Calculate percentage of items received"""
        if obj.items.exists():
            total_quantity = obj.items.aggregate(total=Sum('quantity'))['total'] or 0
            received_quantity = obj.items.aggregate(received=Sum('received_quantity'))['received'] or 0
            if total_quantity > 0:
                return int((received_quantity / total_quantity) * 100)
        return 0
    
    def validate(self, data):
        """Validate purchase order data"""
        expected_delivery = data.get('expected_delivery_date')
        if expected_delivery and expected_delivery < timezone.now().date():
            raise serializers.ValidationError({
                "expected_delivery_date": "Expected delivery date cannot be in the past."
            })
        return data


class PurchaseOrderCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating purchase orders with items"""
    items = PurchaseOrderItemSerializer(many=True, required=True)
    
    class Meta:
        model = PurchaseOrder
        fields = [
            'supplier', 'expected_delivery_date',
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
    
    def create(self, validated_data):
        """Create purchase order with items"""
        items_data = validated_data.pop('items')
        tenant = self.context.get('tenant')
        request = self.context.get('request')
        
        # Generate PO number
        po_count = PurchaseOrder.objects.filter(tenant=tenant).count() + 1
        po_number = f"PO-{timezone.now().year}{po_count:06d}"
        
        # Create purchase order
        purchase_order = PurchaseOrder.objects.create(
            tenant=tenant,
            po_number=po_number,
            created_by=request.user if request else None,
            **validated_data
        )
        
        # Create items
        total = 0
        for item_data in items_data:
            product = item_data.get('product')
            quantity = item_data.get('quantity')
            unit_price = item_data.get('unit_price')
            total_price = quantity * unit_price
            total += total_price
            
            PurchaseOrderItem.objects.create(
                purchase_order=purchase_order,
                total_price=total_price,
                **item_data
            )
        
        # Update totals
        purchase_order.subtotal = total
        purchase_order.total_amount = total
        purchase_order.save(update_fields=['subtotal', 'total_amount'])
        
        return purchase_order
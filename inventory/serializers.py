# apps/inventory/serializers.py
from rest_framework import serializers
from django.db.models import Sum, F, Q
from django.utils import timezone
from .models import (
    Product, Category, Unit, StockMovement, InventoryAlert
)
from apps.tenants.models import Tenant

class CategorySerializer(serializers.ModelSerializer):
    """Category serializer"""
    product_count = serializers.SerializerMethodField()
    parent_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Category
        fields = [
            'id', 'tenant', 'name', 'description', 'parent',
            'parent_name', 'icon', 'color', 'is_active',
            'product_count', 'created_by', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']
    
    def get_product_count(self, obj):
        return obj.products.count()
    
    def get_parent_name(self, obj):
        return obj.parent.name if obj.parent else None
    
    def validate_name(self, value):
        """Validate category name is unique for tenant"""
        tenant = self.context.get('tenant') or self.instance.tenant if self.instance else None
        if tenant and Category.objects.filter(tenant=tenant, name=value).exclude(id=self.instance.id if self.instance else None).exists():
            raise serializers.ValidationError("A category with this name already exists.")
        return value


class UnitSerializer(serializers.ModelSerializer):
    """Unit serializer"""
    class Meta:
        model = Unit
        fields = ['id', 'tenant', 'name', 'abbreviation', 'created_at']
        read_only_fields = ['id', 'created_at']
    
    def validate_name(self, value):
        """Validate unit name is unique for tenant"""
        tenant = self.context.get('tenant') or self.instance.tenant if self.instance else None
        if tenant and Unit.objects.filter(tenant=tenant, name=value).exclude(id=self.instance.id if self.instance else None).exists():
            raise serializers.ValidationError("A unit with this name already exists.")
        return value


class ProductSerializer(serializers.ModelSerializer):
    """Product serializer with full details"""
    category_name = serializers.SerializerMethodField()
    unit_name = serializers.SerializerMethodField()
    is_low_stock = serializers.SerializerMethodField()
    total_value = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = [
            'id', 'tenant', 'name', 'sku', 'barcode', 'description',
            'category', 'category_name', 'unit', 'unit_name',
            'quantity', 'min_quantity', 'max_quantity',
            'reorder_point', 'reorder_quantity',
            'purchase_price', 'selling_price', 'wholesale_price',
            'discount_price', 'batch_number', 'expiry_date',
            'manufacturing_date', 'location', 'shelf_number',
            'image', 'image_url', 'gallery_images',
            'status', 'is_featured', 'is_active',
            'weight', 'dimensions',
            'is_low_stock', 'total_value',
            'created_by', 'created_by_name',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'tenant', 'created_by', 'created_at', 'updated_at'
        ]
    
    def get_category_name(self, obj):
        return obj.category.name if obj.category else None
    
    def get_unit_name(self, obj):
        return obj.unit.name if obj.unit else None
    
    def get_is_low_stock(self, obj):
        return obj.is_low_stock()
    
    def get_total_value(self, obj):
        return obj.quantity * obj.purchase_price
    
    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() if obj.created_by else None
    
    def get_image_url(self, obj):
        if obj.image and hasattr(obj.image, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None
    
    def validate_sku(self, value):
        """Validate SKU is unique for tenant"""
        tenant = self.context.get('tenant') or self.instance.tenant if self.instance else None
        if tenant and Product.objects.filter(tenant=tenant, sku=value).exclude(id=self.instance.id if self.instance else None).exists():
            raise serializers.ValidationError("A product with this SKU already exists.")
        return value
    
    def validate_barcode(self, value):
        """Validate barcode is unique for tenant"""
        if value:
            tenant = self.context.get('tenant') or self.instance.tenant if self.instance else None
            if tenant and Product.objects.filter(tenant=tenant, barcode=value).exclude(id=self.instance.id if self.instance else None).exists():
                raise serializers.ValidationError("A product with this barcode already exists.")
        return value
    
    def validate(self, data):
        """Validate product data"""
        # Check selling price >= purchase price
        if data.get('selling_price') and data.get('purchase_price'):
            if data['selling_price'] < data['purchase_price']:
                raise serializers.ValidationError({
                    "selling_price": "Selling price cannot be less than purchase price."
                })
        return data
    
    def create(self, validated_data):
        """Create product with tenant and created_by"""
        tenant = self.context.get('tenant')
        request = self.context.get('request')
        
        if tenant:
            validated_data['tenant'] = tenant
        if request and hasattr(request, 'user'):
            validated_data['created_by'] = request.user
        
        return super().create(validated_data)


class ProductListSerializer(serializers.ModelSerializer):
    """Lightweight product serializer for listing"""
    category_name = serializers.SerializerMethodField()
    is_low_stock = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'sku', 'barcode', 'category_name',
            'quantity', 'reorder_point', 'selling_price',
            'status', 'is_low_stock', 'image'
        ]
    
    def get_category_name(self, obj):
        return obj.category.name if obj.category else None
    
    def get_is_low_stock(self, obj):
        return obj.is_low_stock()


class StockMovementSerializer(serializers.ModelSerializer):
    """Stock movement serializer"""
    product_name = serializers.SerializerMethodField()
    product_sku = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    
    class Meta:
        model = StockMovement
        fields = [
            'id', 'tenant', 'product', 'product_name', 'product_sku',
            'movement_type', 'quantity', 'previous_quantity',
            'new_quantity', 'unit_price', 'total_price',
            'reference', 'notes', 'created_by', 'created_by_name',
            'created_at'
        ]
        read_only_fields = [
            'id', 'tenant', 'created_by', 'created_at'
        ]
    
    def get_product_name(self, obj):
        return obj.product.name if obj.product else None
    
    def get_product_sku(self, obj):
        return obj.product.sku if obj.product else None
    
    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() if obj.created_by else None
    
    def validate(self, data):
        """Validate stock movement"""
        product = data.get('product')
        movement_type = data.get('movement_type')
        quantity = data.get('quantity')
        
        # Check if product exists
        if not product:
            raise serializers.ValidationError("Product is required.")
        
        # For sales, check if enough stock
        if movement_type == 'sale' and quantity > product.quantity:
            raise serializers.ValidationError({
                "quantity": f"Insufficient stock. Available: {product.quantity}"
            })
        
        # Calculate new quantity
        previous_quantity = product.quantity
        if movement_type in ['purchase', 'return']:
            new_quantity = previous_quantity + quantity
        elif movement_type in ['sale', 'waste']:
            new_quantity = previous_quantity - quantity
        else:  # adjustment
            new_quantity = quantity
        
        data['previous_quantity'] = previous_quantity
        data['new_quantity'] = new_quantity
        
        return data
    
    def create(self, validated_data):
        """Create stock movement and update product quantity"""
        product = validated_data['product']
        new_quantity = validated_data['new_quantity']
        quantity = validated_data['quantity']
        
        # Update product quantity
        product.quantity = new_quantity
        product.save(update_fields=['quantity', 'updated_at'])
        
        # Set total price
        validated_data['total_price'] = quantity * validated_data.get('unit_price', 0)
        
        # Set tenant
        validated_data['tenant'] = product.tenant
        
        # Set created_by
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['created_by'] = request.user
        
        # Create stock movement
        movement = super().create(validated_data)
        
        # Check for low stock alert
        if product.is_low_stock():
            InventoryAlert.objects.create(
                tenant=product.tenant,
                product=product,
                alert_type='low_stock',
                message=f"Product {product.name} is low on stock. Current quantity: {product.quantity}"
            )
        
        return movement


class InventoryAlertSerializer(serializers.ModelSerializer):
    """Inventory alert serializer"""
    product_name = serializers.SerializerMethodField()
    product_sku = serializers.SerializerMethodField()
    
    class Meta:
        model = InventoryAlert
        fields = [
            'id', 'tenant', 'product', 'product_name', 'product_sku',
            'alert_type', 'message', 'is_read', 'is_resolved',
            'created_at', 'resolved_at'
        ]
        read_only_fields = ['id', 'tenant', 'created_at']
    
    def get_product_name(self, obj):
        return obj.product.name if obj.product else None
    
    def get_product_sku(self, obj):
        return obj.product.sku if obj.product else None


class ProductStockUpdateSerializer(serializers.Serializer):
    """Serializer for updating product stock"""
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2, required=True)
    movement_type = serializers.ChoiceField(choices=StockMovement.MOVEMENT_TYPES, required=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, default=0)
    
    def validate_quantity(self, value):
        """Validate quantity is positive"""
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than zero.")
        return value
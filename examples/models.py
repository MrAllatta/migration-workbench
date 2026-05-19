from django.db import models


class ExampleCrop(models.Model):
    name = models.CharField(max_length=200, unique=True)
    crop_type = models.CharField(max_length=100, blank=True, default="")

    def __str__(self):
        return self.name


class ExampleBlock(models.Model):
    name = models.CharField(max_length=200, unique=True)
    block_type = models.CharField(max_length=50, default="field")
    num_beds = models.IntegerField(default=0)
    bed_width_feet = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    bedfeet_per_bed = models.IntegerField(default=0)

    def __str__(self):
        return self.name


class ExampleFarm(models.Model):
    """A farm entity that groups fields and varieties."""

    name = models.CharField(max_length=200, unique=True)
    region = models.CharField(max_length=100, blank=True, default="")
    established_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.name


class ExampleField(models.Model):
    """A field belonging to a farm with an acreage measurement."""

    name = models.CharField(max_length=200)
    farm = models.ForeignKey(ExampleFarm, on_delete=models.CASCADE)
    acreage = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("name", "farm")]

    def __str__(self):
        return self.name


class ExampleVariety(models.Model):
    """A crop variety that may be associated with a farm."""

    name = models.CharField(max_length=200, unique=True)
    crop = models.ForeignKey(
        ExampleCrop, on_delete=models.CASCADE, related_name="varieties"
    )
    farm = models.ForeignKey(
        ExampleFarm,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="varieties",
    )
    seed_cost = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    full_description = models.TextField(blank=True, default="")

    def __str__(self):
        return self.name

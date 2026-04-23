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

from django.db import models

class Game(models.Model):
    appid = models.BigIntegerField(primary_key=True)
    name = models.TextField()
    description = models.TextField(blank=True)
    genres = models.JSONField(default=list)
    user_tags = models.JSONField(default=list)
    review_count = models.PositiveIntegerField(default=0)
    recommended_count = models.PositiveIntegerField(default=0)

    @property
    def steam_url(self):
        return f"https://store.steampowered.com/app/{self.appid}/"

class Review(models.Model):
    id = models.CharField(primary_key=True, max_length=64)
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="reviews")
    text = models.TextField()
    voted_up = models.BooleanField()
    timestamp_created = models.BigIntegerField(default=0)
    votes_up = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict)

    class Meta:
        indexes = [models.Index(fields=["game", "-votes_up", "id"], name="review_game_helpful_idx")]

class GameInsight(models.Model):
    game = models.OneToOneField(Game, primary_key=True, on_delete=models.CASCADE, related_name="insight")
    analysis_version = models.CharField(max_length=80)
    analyzed_count = models.PositiveIntegerField()
    positive = models.JSONField(default=list)
    negative = models.JSONField(default=list)
    prepared_at = models.DateTimeField(auto_now=True)

class DatasetState(models.Model):
    key = models.CharField(primary_key=True, max_length=40)
    fingerprint = models.CharField(max_length=64)
    metadata = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

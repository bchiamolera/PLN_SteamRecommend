from rest_framework import serializers
from .models import Game
from steam_discovery.retrieval import MODES

class SearchQuerySerializer(serializers.Serializer):
    q = serializers.CharField(max_length=500, allow_blank=False, trim_whitespace=True)
    limit = serializers.IntegerField(default=10, min_value=1, max_value=50)
    mode = serializers.ChoiceField(choices=MODES, default='word2vec')
    required_tag = serializers.ListField(child=serializers.CharField(max_length=100), required=False, default=list, max_length=30)
    excluded_tag = serializers.ListField(child=serializers.CharField(max_length=100), required=False, default=list, max_length=30)
    genre = serializers.ListField(child=serializers.CharField(max_length=100), required=False, default=list, max_length=30)

class GameSerializer(serializers.ModelSerializer):
    steam_url = serializers.ReadOnlyField()

    class Meta:
        model = Game
        fields = ["appid", "name", "description", "genres", "user_tags", "steam_url", "review_count", "recommended_count"]

class EvidenceSerializer(serializers.Serializer):
    review_id = serializers.CharField()
    excerpt = serializers.CharField()

class AspectSerializer(serializers.Serializer):
    aspect = serializers.CharField()
    summary = serializers.CharField()
    support_count = serializers.IntegerField()
    evidence = EvidenceSerializer(many=True)

class InsightSerializer(serializers.Serializer):
    appid = serializers.IntegerField()
    analysis_version = serializers.CharField()
    status = serializers.ChoiceField(choices=["ready", "not_prepared", "no_reviews", "insufficient_evidence"])
    collected_review_count = serializers.IntegerField()
    analyzed_review_count = serializers.IntegerField()
    positive = AspectSerializer(many=True)
    negative = AspectSerializer(many=True)
    note = serializers.CharField()

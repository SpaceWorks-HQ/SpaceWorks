from rest_framework import serializers


class OidcBrowserStartSerializer(serializers.Serializer):
    redirect_uri = serializers.URLField(max_length=2048)
    email = serializers.EmailField(required=False, allow_blank=True)
    makerspace_slug = serializers.SlugField(required=False, allow_blank=True)


class OidcBrowserStartResponseSerializer(serializers.Serializer):
    authorization_url = serializers.URLField()
    state = serializers.CharField()
    nonce = serializers.CharField()
    expires_in = serializers.IntegerField()


class OidcBrowserCallbackSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=4096, trim_whitespace=True)
    state = serializers.CharField(max_length=512, trim_whitespace=True)
    nonce = serializers.CharField(max_length=512, trim_whitespace=True)


class OidcBrowserLoginResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    user = serializers.DictField()
    outcome = serializers.CharField()

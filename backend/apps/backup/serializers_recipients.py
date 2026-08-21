from rest_framework import serializers

from .models import MakerspaceArchiveRecipient


class ArchiveRecipientSerializer(serializers.ModelSerializer):
    class Meta:
        model = MakerspaceArchiveRecipient
        fields = (
            "id",
            "public_recipient",
            "fingerprint",
            "label",
            "added_by",
            "added_at",
            "revoked_at",
            "compromised_at",
            "verified_at",
            "challenge_issued_at",
        )
        read_only_fields = fields


class ArchiveRecipientCreateSerializer(serializers.Serializer):
    public_recipient = serializers.CharField(max_length=200)
    label = serializers.CharField(max_length=120)


class ArchiveRecipientVerifySerializer(serializers.Serializer):
    nonce = serializers.CharField(
        max_length=128,
        help_text=(
            "The decrypted 32-byte nonce in canonical, unpadded base64url form. "
            "Padding and non-canonical encodings are refused."
        ),
    )


class ArchiveRecipientChallengeSerializer(serializers.Serializer):
    recipient = ArchiveRecipientSerializer()
    encrypted_challenge = serializers.CharField(
        help_text=(
            "The binary age ciphertext encoded as unpadded base64url for JSON transport. "
            "Its decrypted plaintext is the 32-byte nonce encoded as canonical, unpadded "
            "base64url."
        )
    )
    nonce_encoding = serializers.CharField(
        default="base64url-unpadded",
        help_text="The decrypted nonce uses canonical unpadded base64url.",
    )


class ArchiveRecipientErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()
    code = serializers.CharField()

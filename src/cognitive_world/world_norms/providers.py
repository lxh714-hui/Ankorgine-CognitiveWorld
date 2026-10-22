"""Optional WorldNorms draft generation using the existing provider transport."""

from dataclasses import dataclass

from cognitive_world.resolution.providers import OpenAICompatibleCausalProvider
from cognitive_world.resolution.provider_budget import claim_provider_call, provider_call_scope


@dataclass(frozen=True)
class OpenAICompatibleNormsDraftProvider:
    transport: OpenAICompatibleCausalProvider

    def generate_norms_draft(self, world_seed: str, *, max_output_chars: int) -> str:
        if not isinstance(world_seed, str) or len(world_seed) > 8_000:
            raise ValueError("world seed exceeds generation bounds")
        with provider_call_scope():
            if not claim_provider_call():
                raise TimeoutError("WorldNorms provider-call budget is exhausted")
            return self.transport.complete_structured(
                "Create a structured WorldNorms draft for the supplied fictional setting. Return only JSON matching the WorldNorms schema requested by the caller. State explicitly when no formal law exists. Keep legality distinct from morality. Do not claim that this draft is trusted, do not add safety exemptions, and do not treat hidden rules as public. The application will validate every field and rule.",
                {"world_seed": world_seed},
                max_output_chars=min(max_output_chars, 8_000),
            )

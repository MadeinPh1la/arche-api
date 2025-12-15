import pytest

from arche_api.application.use_cases.external_apis.edgar.parse_xbrl_file import (
    ParseXBRLFileRequest,
    ParseXBRLFileUseCase,
)
from arche_api.domain.entities.xbrl_document import (
    XBRLContext,
    XBRLDocument,
    XBRLFact,
    XBRLPeriod,
    XBRLUnit,
)


class _FakeXBRLParserGateway:
    async def parse_xbrl(
        self,
        *,
        accession_id: str,
        content: bytes | str,
    ) -> XBRLDocument:
        period = XBRLPeriod(
            is_instant=True,
            instant_date=None,
            start_date=None,
            end_date=None,
        )
        ctx = XBRLContext(
            id="C1",
            entity_identifier="0000000000",
            period=period,
            dimensions=(),
        )
        unit = XBRLUnit(id="U1", measure="USD")
        fact = XBRLFact(
            id=None,
            concept_qname="us-gaap:Revenues",
            context_ref="C1",
            unit_ref="U1",
            raw_value="123",
            decimals=None,
            precision=None,
            is_nil=False,
            footnote_refs=(),
        )
        return XBRLDocument(
            accession_id=accession_id,
            contexts={"C1": ctx},
            units={"U1": unit},
            facts=(fact,),
        )


@pytest.mark.asyncio
async def test_parse_xbrl_file_use_case_round_trip() -> None:
    gateway = _FakeXBRLParserGateway()
    uc = ParseXBRLFileUseCase(parser=gateway)

    req = ParseXBRLFileRequest(
        cik="0000000000",
        accession_id="0000000000-00-000000",
        content=b"<xbrl/>",
    )

    result = await uc.execute(req)

    assert result.document.accession_id == req.accession_id
    assert len(result.document.facts) == 1
    assert result.document.facts[0].concept_qname == "us-gaap:Revenues"

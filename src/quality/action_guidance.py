from __future__ import annotations


def quality_issue_actions(quality_issues: list[dict]) -> list[str]:
    codes = {issue.get("code", "") for issue in quality_issues}
    actions = []
    if {"weak_related_guides", "weak_related_guide_links"} & codes:
        actions.append(
            "품질검수에서 Related Guides 내부 링크 문제가 감지되었습니다. Windows 글 템플릿과 related_guides 생성기가 "
            "블로그 내부 검색 링크 3개 이상을 출력하는지 확인하세요."
        )
    if {
        "missing_required_image_assets",
        "missing_images",
        "weak_image_plan",
        "weak_image_alt_text",
        "weak_image_caption",
    } & codes:
        actions.append(
            "품질검수에서 이미지 문제가 감지되었습니다. hero/inline 이미지 2개, strict image_plan, 주제와 연결된 alt/caption이 "
            "생성됐는지 확인하세요."
        )
    if {"weak_sources", "weak_microsoft_sources", "missing_microsoft_source", "shallow_microsoft_sources"} & codes:
        actions.append(
            "품질검수에서 공식 출처 문제가 감지되었습니다. Microsoft Support/Learn 직접 링크와 주제별 공식 출처를 보강하세요."
        )
    return actions

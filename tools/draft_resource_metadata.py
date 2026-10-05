"""Apply bounded, source-grounded offline drafts. No publication or OSS writes."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Titles and editions read visually from first-page contact sheets. Names are
# omitted unless clearly readable; original_filename remains unchanged.
DRAFTS = {
    "cpp-programming": ("C++程序设计", None, "程序设计", "封面显示书名为《C++程序设计》。本资料为该书的PDF版本，作者姓名与具体章节范围待进一步核对。", []),
    "fundamentals-of-aerodynamics": ("Fundamentals of Aerodynamics", "第6版", "气动与热学", "John Anderson的空气动力学教材，封面标注为第6版。资料为英文PDF；本次未据目录核对章节范围。", ["John Anderson"]),
    "sensor-principles-and-applications": ("传感器原理及应用", "第4版", "电路与电子", "以传感器原理与应用为主题的教材，封面标注第4版。本次核对了封面，详细内容范围以原书为准。", []),
    "heat-transfer-4th-edition": ("传热学", "第4版", "气动与热学", "杨世铭、陶文铨编著的《传热学》，封面标注第4版。资料为原书PDF，具体章节与例题范围未在本次逐项核对。", ["杨世铭", "陶文铨"]),
    "signals-and-systems": ("信号与系统", "第3版", "控制与信号", "段哲民主编的《信号与系统》，封面标注第3版。资料为该教材的PDF版本，详细介绍待目录核对后补充。", ["段哲民"]),
    "solid-rocket-motor-design": ("固体火箭发动机设计", None, "航天推进", "《固体火箭发动机设计》PDF教材，封面书名已核对。本次不根据书名补写设计步骤、参数或未经查证的章节。", []),
    "solid-rocket-propellants": ("固体火箭推进剂", None, "航天推进", "王英红主编的课程材料，书名页署西北工业大学。目录涉及推进剂分类、性能及燃烧等主题；资料形态为讲义，第一页为书名页。", ["王英红"]),
    "multidimensional-gasdynamics-3rd-edition": ("多维气体动力学基础", "第3版", "气动与热学", "封面书名为《多维气体动力学基础》，标注第3版。资料为该教材的PDF版本，本次尚未确认完整作者信息与具体章节。", []),
    "guidance-systems-lecture-notes": ("导引系统原理笔记", None, "控制与信号", "按名称映射整理的导引系统原理手写笔记，第一页为带批注的学习内页。编写者未确认，不能当成正式出版教材或采用内页冒充封面。", []),
    "guidance-systems": ("导引系统原理", None, "控制与信号", "本资料从《导弹导引系统导论》正文开始，介绍导引系统的基本含义和类别。名称沿用本地映射；作者、版本和正式封面未确认。", []),
    "introduction-to-missile-system-design": ("导弹总体设计导论", None, "飞行器工程", "《导弹总体设计导论》PDF教材，封面书名已核对。这里只整理题名与资料信息，未据正文核对详细内容范围。", []),
    "engineering-math-complex-analysis": ("工程数学：复变函数", "第5版", "数学与力学", "复变函数教材第5版，内容提要涉及解析函数、积分、级数、留数及共形映射。新版保留原教材体系，每章设有内容小结。", []),
    "engineering-math-integral-transforms": ("工程数学：积分变换", "第4版", "数学与力学", "《工程数学：积分变换》PDF教材，封面标注第4版。资料主题与版本已据封面核对，作者信息与章节范围仍待确认。", []),
    "engineering-thermodynamics-5th-edition": ("工程热力学", "第5版", "气动与热学", "《工程热力学》PDF教材，封面标注第5版。本次确认书名和版次，未仅凭原文件名补入作者或出版年份。", []),
    "tactical-missile-and-solid-rocket-motor-overview": ("战术导弹与火箭固体发动机技术概论", None, "航天推进", "《战术导弹与火箭固体发动机技术概论》PDF教材，书名依据实际封面整理。具体章节范围与编著信息待进一步核对。", []),
    "numerical-analysis-2nd-edition": ("数值分析", "第2版", "数学与力学", "《数值分析》PDF教材，实际封面标注第2版。作者与具体章节未在本次核对，介绍仅保留已确认的题名和版本信息。", []),
    "digital-electronics-fundamentals": ("数字电子技术基础", "第6版", "电路与电子", "《数字电子技术基础》PDF教材，实际封面标注第6版。资料归入电子技术基础，详细作者与章节信息尚待核对。", []),
    "mechanics-of-materials-3rd-edition": ("材料力学", "第3版", "数学与力学", "《材料力学》PDF教材，封面标注第3版。资料按力学基础整理，作者与详细章节范围未在本次逐项确认。", []),
    "gasdynamics-fundamentals": ("气体动力学基础", None, "气动与热学", "《气体动力学基础》PDF教材，实际封面书名已核对。本次仅整理已确认的题名，未据书名推断章节和适用专业。", []),
    "rocket-engine-fundamentals": ("火箭发动机理论基础", "第2版", "航天推进", "《火箭发动机理论基础》PDF教材，实际封面标注第2版。作者与完整章节范围仍待核对，本次不补写未经证实的参数或方法。", []),
    "modern-missile-guidance-and-control": ("现代导弹制导控制", None, "控制与信号", "《现代导弹制导控制》PDF教材，封面书名已核对。资料按控制相关主题整理，编著信息与详细内容范围待进一步确认。", []),
    "modern-control-theory-3rd-edition": ("现代控制理论", "第3版", "控制与信号", "刘豹、唐万生主编的现代控制理论教材第3版。内容提要涉及状态空间、能控性与能观性、稳定性、反馈控制及最优控制等主题。", ["刘豹", "唐万生"]),
    "theoretical-mechanics-nwpu": ("理论力学", "第3版", "数学与力学", "《理论力学》PDF教材，实际封面标注第3版。原文件名称中的“西工大版本”保留为内部映射依据，不作为正式书名的一部分。", []),
    "circuit-analysis-fundamentals": ("电路分析基础", None, "电路与电子", "《电路分析基础》PDF教材，书名依据实际封面整理。作者和版本待确认，本次不把文件名括号中的人名当成已核验信息。", []),
    "spacecraft-attitude-orbit-control": ("航天器姿态与轨道控制原理", None, "飞行器工程", "《航天器姿态与轨道控制原理》PDF教材，实际封面书名已核对。具体章节、编著信息与出版年份仍待确认。", []),
    "space-propulsion-technology": ("航天推进技术", None, "航天推进", "《航天推进技术》PDF教材，实际封面书名已核对。本次仅整理题名与格式信息，详细内容介绍待核对目录后完善。", []),
    "propulsion-thermal-protection-fundamentals": ("航天推进热防护基础", None, "航天推进", "本书介绍航天推进系统的热防护，覆盖传热、热防护材料、烧蚀与热结构等主题。内容简介还涉及液体火箭发动机和冲压发动机的热防护；第一页为书名页。", ["李江", "刘洋", "石磊", "景婷婷", "王德", "孙冰", "陈军"]),
    "space-flight-dynamics": ("航天飞行动力学", None, "飞行器工程", "《航天飞行动力学》PDF教材，封面书名已核对。本次归入飞行器工程资料，作者与具体章节范围待进一步确认。", []),
}


def main():
    candidate_path = ROOT / "docs/research/resources-preparation/resources.candidates.json"
    items = json.loads(candidate_path.read_text(encoding="utf-8"))
    extracts = {x['id']: x for x in json.loads((ROOT / "artifacts/resources-preparation/extraction-index.json").read_text(encoding="utf-8"))}
    no_cover = {"guidance-systems-lecture-notes": "internal_page", "guidance-systems": "internal_page",
                "solid-rocket-propellants": "title_page", "propulsion-thermal-protection-fundamentals": "title_page"}
    upload = []
    lines = ["# 资料元数据与封面审核草稿", "", "日期：2026-10-05。28份草稿，全部未发布。25份网络核验按用户要求跳过；三本人工下载已通过。", "",
             "24份封面候选可上传，4份需确认封面页或是否采用书名页。介绍以封面及最多前4页为依据；未核对目录的条目采用简短资料说明，不凑写章节。分类是建议，仍待审核。", "",
             "| 书名 | 版本 | 建议分类 | 封面 | 介绍草稿 |", "|---|---|---|---|---|"]
    for item in items:
        if item['id'] not in DRAFTS:
            continue
        if item['review']['metadata_status'] == 'approved' or item['published']:
            raise ValueError("Refusing to overwrite approved metadata")
        title, edition, category, description, authors = DRAFTS[item['id']]
        item.update(title=title, edition=edition, category=category, description_short=description,
                    description=description, authors=authors, language='en' if item['id']=='fundamentals-of-aerodynamics' else 'zh',
                    tags=[category, title], source_note="根据用户提供的本地PDF封面或前4页整理；详细书目信息与发布说明待审核。")
        record = extracts[item['id']]
        review = item['review']
        if review['remote_status'] != 'manual_download_passed':
            review['remote_status'] = 'verification_waived_by_user'
            review['remote_check_waiver'] = {'on':'2026-10-05', 'scope':'remaining_25_oss_objects', 'reason':'user_requested_skip'}
        review.update(metadata_status='draft', cover_status=no_cover.get(item['id'], 'visually_checked_candidate'),
                      evidence_pages=[1, 2, 3, 4], evidence_file=f"artifacts/resources-preparation/{item['id']}.evidence.json",
                      proposed_cover_key=None if item['id'] in no_cover else f"public/covers/{item['id']}-v1.jpg")
        # No actual cover_key until upload/public access is confirmed.
        if item['id'] not in no_cover:
            upload.append({'id':item['id'], 'local_path':f"artifacts/resources-preparation/{record['cover_filename']}",
                           'object_key':review['proposed_cover_key'], 'size_bytes':record['cover_size_bytes'], 'uploaded':False})
        label = {'internal_page':'正文或笔记内页（待补图）', 'title_page':'书名页（待确认）'}.get(no_cover.get(item['id']), '封面候选')
        label = f"[{label}](../../../artifacts/resources-preparation/{record['cover_filename']})"
        lines.append(f"| {title} | {edition or '未确认'} | {category} | {label} | {description} |")
    candidate_path.write_text(json.dumps(items, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
    output = ROOT / "docs/research/resources-preparation"
    (output / "cover-upload-manifest.json").write_text(json.dumps(upload, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
    lines.extend(['', '## 封面总览', '', *[f'![封面候选总览 {n}](../../../artifacts/resources-preparation/contact-{n}.jpg)' for n in range(1, 5)]])
    (output / "metadata-review.md").write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(f"Prepared {len(DRAFTS)} metadata drafts, {len(upload)} cover candidates; no publication")


if __name__ == '__main__':
    main()

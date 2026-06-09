import asyncio
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont


@dataclass
class ConfigEntry:
    key_name: str
    dot_path: str
    value_text: str
    depth: int


@dataclass
class MessageLine:
    kind: str
    text: str
    label: str = ""


class RenderHelper:
    def __init__(
        self,
        data_dir: Path,
        raw_config_getter: Callable[[str, Any], Any],
        int_config_getter: Callable[[str, int], int],
    ):
        self.data_dir = data_dir
        self._get_raw_config_value = raw_config_getter
        self._get_int_config = int_config_getter

    async def render_text_card(
        self,
        title: str,
        message: str,
        subtitle: str = "",
        filename_prefix: str = "message",
    ) -> Path:
        return await asyncio.to_thread(
            self._render_text_card_sync,
            title,
            message,
            subtitle,
            filename_prefix,
        )

    async def render_config_table(
        self,
        plugin_name: str,
        config_path: Path,
        entries: list[ConfigEntry],
    ) -> Path:
        return await asyncio.to_thread(
            self._render_config_table_sync,
            plugin_name,
            config_path,
            entries,
        )

    def _render_text_card_sync(
        self,
        title: str,
        message: str,
        subtitle: str,
        filename_prefix: str,
    ) -> Path:
        render_dir = self._get_render_dir()
        render_dir.mkdir(parents=True, exist_ok=True)
        self._trim_rendered_images(render_dir)

        canvas_width = max(860, self._get_int_config("image_width", 1600))
        margin = 40
        title_font = self._load_font(30)
        subtitle_font = self._load_font(18)
        section_font = self._load_font(18)
        body_font = self._load_font(20)
        badge_font = self._load_font(16)

        draw = ImageDraw.Draw(Image.new("RGB", (canvas_width, 10), "#FFFFFF"))
        title_height = self._line_height(draw, title_font)
        subtitle_height = self._line_height(draw, subtitle_font) if subtitle else 0
        content_width = canvas_width - margin * 2 - 32
        content_items = self._layout_message_lines(
            draw=draw,
            message=message,
            body_font=body_font,
            section_font=section_font,
            badge_font=badge_font,
            content_width=content_width,
        )
        body_height = sum(item["height"] for item in content_items) + max(0, len(content_items) - 1) * 10

        header_height = 96 + subtitle_height
        card_top = 24
        card_bottom = header_height + body_height + 88
        image_height = card_bottom + 24

        image = Image.new("RGB", (canvas_width, image_height), "#F6F4EE")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (24, card_top, canvas_width - 24, card_bottom),
            radius=24,
            fill="#FFFDF7",
            outline="#D8D1C0",
            width=2,
        )
        draw.text((margin, 44), title, fill="#1F2937", font=title_font)
        current_y = 44 + title_height + 8
        if subtitle:
            draw.text((margin, current_y), subtitle, fill="#64748B", font=subtitle_font)
            current_y += subtitle_height + 14

        draw.rounded_rectangle(
            (margin, current_y, canvas_width - margin, card_bottom - 32),
            radius=16,
            fill="#F8FAFC",
            outline="#E2E8F0",
            width=1,
        )
        content_y = current_y + 16
        for item in content_items:
            self._draw_message_item(
                draw=draw,
                item=item,
                x=margin + 16,
                y=content_y,
                width=content_width,
                body_font=body_font,
                section_font=section_font,
                badge_font=badge_font,
            )
            content_y += item["height"] + 10

        output_path = render_dir / self._build_filename(filename_prefix, "png")
        image.save(output_path, format="PNG")
        return output_path

    def _render_config_table_sync(
        self,
        plugin_name: str,
        config_path: Path,
        entries: list[ConfigEntry],
    ) -> Path:
        render_dir = self._get_render_dir()
        render_dir.mkdir(parents=True, exist_ok=True)
        self._trim_rendered_images(render_dir)

        max_rows = max(1, self._get_int_config("image_max_rows", 300))
        was_truncated = len(entries) > max_rows
        visible_entries = entries[:max_rows]
        max_depth = max((entry.depth for entry in visible_entries), default=0)

        canvas_width = max(960, self._get_int_config("image_width", 1600))
        margin = 40
        header_height = 156
        row_padding_y = 14
        cell_padding_x = 12
        row_gap = 1
        col_key = 560
        col_value = canvas_width - margin * 2 - col_key
        if col_value < 280:
            raise ValueError("图片宽度过小，无法渲染配置表。")

        title_font = self._load_font(30)
        meta_font = self._load_font(18)
        header_font = self._load_font(20)
        body_font = self._load_font(18)
        badge_font = self._load_font(16)
        draw = ImageDraw.Draw(Image.new("RGB", (canvas_width, 10), "#FFFFFF"))

        rows: list[dict[str, Any]] = []
        for entry in visible_entries:
            indent_width = min(entry.depth, 6) * 22
            key_text_width = col_key - cell_padding_x * 2 - 50 - indent_width
            key_lines = self._wrap_text(
                draw,
                entry.dot_path,
                body_font,
                max(80, key_text_width),
            )
            value_lines = self._wrap_text(
                draw,
                entry.value_text,
                body_font,
                col_value - cell_padding_x * 2,
            )
            line_count = max(len(key_lines), len(value_lines))
            line_height = self._line_height(draw, body_font)
            row_height = row_padding_y * 2 + line_count * line_height
            rows.append(
                {
                    "key_lines": key_lines,
                    "value_lines": value_lines,
                    "height": row_height,
                    "depth": entry.depth,
                    "indent_width": indent_width,
                }
            )

        table_header_height = 48
        image_height = header_height + table_header_height
        image_height += sum(row["height"] + row_gap for row in rows)

        image = Image.new("RGB", (canvas_width, image_height), "#F6F4EE")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (24, 20, canvas_width - 24, image_height - 20),
            radius=24,
            fill="#FFFDF7",
            outline="#D8D1C0",
            width=2,
        )
        draw.text((margin, 34), f"Plugin Config: {plugin_name}", fill="#1F2937", font=title_font)
        draw.text((margin, 68), "Flattened view for config keys", fill="#64748B", font=meta_font)

        meta_box_top = 94
        meta_box_bottom = 134
        draw.rounded_rectangle(
            (margin, meta_box_top, canvas_width - margin, meta_box_bottom),
            radius=14,
            fill="#F3F6FB",
            outline="#D6DEEB",
            width=1,
        )
        draw.text(
            (margin + 18, meta_box_top + 10),
            f"文件: {config_path.name}",
            fill="#334155",
            font=meta_font,
        )
        draw.text(
            (canvas_width - margin - 320, meta_box_top + 10),
            f"条目数: {len(visible_entries)}/{len(entries)}  层级深度: {max_depth + 1}",
            fill="#475569",
            font=meta_font,
        )

        table_top = header_height
        table_left = margin
        table_right = canvas_width - margin
        draw.rounded_rectangle(
            (table_left, table_top, table_right, table_top + table_header_height),
            radius=16,
            fill="#DDE8F7",
            outline="#C1D0E6",
            width=1,
        )

        key_x = table_left
        value_x = key_x + col_key
        header_y = table_top + 12
        draw.text((key_x + cell_padding_x, header_y), "Key", fill="#102A43", font=header_font)
        draw.text((value_x + cell_padding_x, header_y), "Value", fill="#102A43", font=header_font)

        current_y = table_top + table_header_height + row_gap
        line_height = self._line_height(draw, body_font)
        for index, row in enumerate(rows):
            fill = "#FFFFFF" if index % 2 == 0 else "#F7F9FC"
            draw.rectangle(
                (table_left, current_y, table_right, current_y + row["height"]),
                fill=fill,
                outline="#E2E8F0",
                width=1,
            )
            draw.line((value_x, current_y, value_x, current_y + row["height"]), fill="#E2E8F0", width=1)

            accent_color = self._depth_color(row["depth"])
            draw.rounded_rectangle(
                (key_x + 8, current_y + 8, key_x + 14, current_y + row["height"] - 8),
                radius=3,
                fill=accent_color,
            )

            badge_left = key_x + cell_padding_x + 14
            badge_top = current_y + row_padding_y
            badge_right = badge_left + 34
            badge_bottom = badge_top + 22
            draw.rounded_rectangle(
                (badge_left, badge_top, badge_right, badge_bottom),
                radius=8,
                fill=accent_color,
            )
            draw.text(
                (badge_left + 8, badge_top + 2),
                f"L{row['depth'] + 1}",
                fill="#FFFFFF",
                font=badge_font,
            )
            self._draw_multiline_cell(
                draw,
                row["key_lines"],
                key_x + cell_padding_x + 56 + row["indent_width"],
                current_y + row_padding_y,
                body_font,
                line_height,
                "#1F2937",
            )
            self._draw_multiline_cell(
                draw,
                row["value_lines"],
                value_x + cell_padding_x,
                current_y + row_padding_y,
                body_font,
                line_height,
                "#111827",
            )
            current_y += row["height"] + row_gap

        output_path = render_dir / self._build_filename(plugin_name, "png")
        image.save(output_path, format="PNG")
        return output_path

    def _get_render_dir(self) -> Path:
        return self.data_dir / "rendered_configs"

    def _build_filename(self, prefix: str, ext: str) -> str:
        safe_prefix = "".join(char if char.isalnum() or char in "._-" else "_" for char in prefix)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return f"{safe_prefix}_{timestamp}.{ext}"

    def _wrap_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
        max_width: int,
    ) -> list[str]:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        source_lines = normalized.split("\n") or [""]
        wrapped_lines: list[str] = []

        for line in source_lines:
            if not line:
                wrapped_lines.append("")
                continue

            if self._measure_text_width(draw, line, font) <= max_width:
                wrapped_lines.append(line)
                continue

            tokens = [token for token in re.split(r"([._/\-\s]+)", line) if token]
            current = ""
            for token in tokens:
                trial = f"{current}{token}"
                if current and self._measure_text_width(draw, trial, font) > max_width:
                    wrapped_lines.append(current.rstrip())
                    current = token.lstrip()
                    if self._measure_text_width(draw, current, font) <= max_width:
                        continue

                if self._measure_text_width(draw, token, font) <= max_width:
                    current = f"{current}{token}"
                    continue

                if current:
                    wrapped_lines.append(current.rstrip())
                    current = ""

                for piece in self._split_token_by_width(draw, token, font, max_width):
                    if self._measure_text_width(draw, piece, font) <= max_width:
                        wrapped_lines.append(piece)
                    else:
                        current = piece

            if current:
                wrapped_lines.append(current.rstrip())
        return wrapped_lines or [""]

    def _split_token_by_width(
        self,
        draw: ImageDraw.ImageDraw,
        token: str,
        font: ImageFont.ImageFont,
        max_width: int,
    ) -> list[str]:
        parts: list[str] = []
        current = ""
        for char in token:
            trial = current + char
            if current and self._measure_text_width(draw, trial, font) > max_width:
                parts.append(current)
                current = char
            else:
                current = trial
        if current:
            parts.append(current)
        return parts

    def _draw_multiline_cell(
        self,
        draw: ImageDraw.ImageDraw,
        lines: list[str],
        x: int,
        y: int,
        font: ImageFont.ImageFont,
        line_height: int,
        fill: str,
    ):
        for index, line in enumerate(lines):
            draw.text((x, y + index * line_height), line, fill=fill, font=font)

    def _layout_message_lines(
        self,
        draw: ImageDraw.ImageDraw,
        message: str,
        body_font: ImageFont.ImageFont,
        section_font: ImageFont.ImageFont,
        badge_font: ImageFont.ImageFont,
        content_width: int,
    ) -> list[dict[str, Any]]:
        raw_lines = message.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        items: list[dict[str, Any]] = []
        body_line_height = self._line_height(draw, body_font)
        section_line_height = self._line_height(draw, section_font)

        for raw_line in raw_lines:
            line = raw_line.strip()
            if not line:
                items.append({"kind": "spacer", "height": 8})
                continue

            parsed = self._parse_message_line(line)
            if parsed.kind == "section":
                lines = self._wrap_text(draw, parsed.text, section_font, content_width - 20)
                items.append(
                    {
                        "kind": "section",
                        "label": "",
                        "lines": lines,
                        "height": len(lines) * section_line_height + 14,
                    }
                )
                continue

            if parsed.kind == "ordered":
                text_width = content_width - 68
                lines = self._wrap_text(draw, parsed.text, body_font, text_width)
                items.append(
                    {
                        "kind": "ordered",
                        "label": parsed.label,
                        "lines": lines,
                        "height": max(34, len(lines) * body_line_height + 18),
                    }
                )
                continue

            if parsed.kind == "bullet":
                text_width = content_width - 42
                lines = self._wrap_text(draw, parsed.text, body_font, text_width)
                items.append(
                    {
                        "kind": "bullet",
                        "label": parsed.label,
                        "lines": lines,
                        "height": max(28, len(lines) * body_line_height + 12),
                    }
                )
                continue

            if parsed.kind == "kv":
                label_width = min(220, max(110, self._measure_text_width(draw, parsed.label, body_font) + 12))
                value_width = content_width - label_width - 16
                value_lines = self._wrap_text(draw, parsed.text, body_font, value_width)
                items.append(
                    {
                        "kind": "kv",
                        "label": parsed.label,
                        "lines": value_lines,
                        "label_width": label_width,
                        "height": max(34, len(value_lines) * body_line_height + 16),
                    }
                )
                continue

            lines = self._wrap_text(draw, parsed.text, body_font, content_width - 16)
            items.append(
                {
                    "kind": "plain",
                    "label": "",
                    "lines": lines,
                    "height": len(lines) * body_line_height + 12,
                }
            )

        while items and items[-1]["kind"] == "spacer":
            items.pop()
        return items or [{"kind": "plain", "label": "", "lines": [""], "height": body_line_height + 12}]

    def _parse_message_line(self, line: str) -> MessageLine:
        ordered_match = re.match(r"^(\d+)\.\s+(.*)$", line)
        if ordered_match:
            return MessageLine(kind="ordered", label=ordered_match.group(1), text=ordered_match.group(2))

        if line.startswith("- "):
            return MessageLine(kind="bullet", label="•", text=line[2:].strip())

        if line.endswith("：") or line.endswith(":"):
            return MessageLine(kind="section", text=line[:-1].strip())

        kv_match = re.match(r"^([^:：]{1,20})[:：]\s*(.+)$", line)
        if kv_match:
            return MessageLine(kind="kv", label=kv_match.group(1).strip(), text=kv_match.group(2).strip())

        return MessageLine(kind="plain", text=line)

    def _draw_message_item(
        self,
        draw: ImageDraw.ImageDraw,
        item: dict[str, Any],
        x: int,
        y: int,
        width: int,
        body_font: ImageFont.ImageFont,
        section_font: ImageFont.ImageFont,
        badge_font: ImageFont.ImageFont,
    ):
        body_line_height = self._line_height(draw, body_font)
        section_line_height = self._line_height(draw, section_font)

        if item["kind"] == "spacer":
            return

        if item["kind"] == "section":
            draw.rounded_rectangle(
                (x, y, x + width, y + item["height"]),
                radius=12,
                fill="#EEF4FF",
                outline="#D6E4FF",
                width=1,
            )
            self._draw_multiline_cell(
                draw,
                item["lines"],
                x + 14,
                y + 7,
                section_font,
                section_line_height,
                "#1D4ED8",
            )
            return

        if item["kind"] == "ordered":
            draw.rounded_rectangle(
                (x, y, x + width, y + item["height"]),
                radius=12,
                fill="#FFFFFF",
                outline="#E5EAF3",
                width=1,
            )
            badge_left = x + 10
            badge_top = y + 8
            badge_right = badge_left + 34
            badge_bottom = badge_top + 22
            draw.rounded_rectangle(
                (badge_left, badge_top, badge_right, badge_bottom),
                radius=8,
                fill="#2563EB",
            )
            draw.text((badge_left + 10, badge_top + 2), item["label"], fill="#FFFFFF", font=badge_font)
            self._draw_multiline_cell(
                draw,
                item["lines"],
                x + 54,
                y + 8,
                body_font,
                body_line_height,
                "#0F172A",
            )
            return

        if item["kind"] == "bullet":
            draw.ellipse((x + 10, y + 10, x + 18, y + 18), fill="#0F766E")
            self._draw_multiline_cell(
                draw,
                item["lines"],
                x + 30,
                y + 4,
                body_font,
                body_line_height,
                "#0F172A",
            )
            return

        if item["kind"] == "kv":
            draw.rounded_rectangle(
                (x, y, x + width, y + item["height"]),
                radius=12,
                fill="#FFFFFF",
                outline="#E5EAF3",
                width=1,
            )
            draw.rounded_rectangle(
                (x + 8, y + 8, x + 8 + item["label_width"], y + item["height"] - 8),
                radius=10,
                fill="#F1F5F9",
            )
            draw.text((x + 18, y + 10), item["label"], fill="#334155", font=body_font)
            self._draw_multiline_cell(
                draw,
                item["lines"],
                x + 18 + item["label_width"],
                y + 8,
                body_font,
                body_line_height,
                "#0F172A",
            )
            return

        self._draw_multiline_cell(
            draw,
            item["lines"],
            x + 4,
            y + 4,
            body_font,
            body_line_height,
            "#111827",
        )

    def _line_height(self, draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont) -> int:
        bbox = draw.textbbox((0, 0), "Ag测试", font=font)
        return (bbox[3] - bbox[1]) + 6

    def _measure_text_width(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
    ) -> int:
        bbox = draw.textbbox((0, 0), text or " ", font=font)
        return bbox[2] - bbox[0]

    def _depth_color(self, depth: int) -> str:
        palette = [
            "#2563EB",
            "#0F766E",
            "#B45309",
            "#7C3AED",
            "#BE185D",
            "#475569",
        ]
        return palette[min(depth, len(palette) - 1)]

    def _load_font(self, size: int) -> ImageFont.ImageFont:
        configured_font = str(self._get_raw_config_value("font_path", "")).strip()
        font_candidates = []
        if configured_font:
            font_candidates.append(configured_font)
        font_candidates.extend(
            [
                "C:/Windows/Fonts/msyh.ttc",
                "C:/Windows/Fonts/msyhbd.ttc",
                "C:/Windows/Fonts/simhei.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            ]
        )

        for candidate in font_candidates:
            path = Path(candidate)
            if path.exists():
                try:
                    return ImageFont.truetype(str(path), size=size)
                except OSError:
                    continue
        return ImageFont.load_default()

    def _trim_rendered_images(self, render_dir: Path):
        keep_count = max(1, self._get_int_config("render_image_keep_count", 20))
        rendered_files = sorted(render_dir.glob("*.png"), reverse=True)
        for obsolete in rendered_files[keep_count:]:
            obsolete.unlink(missing_ok=True)

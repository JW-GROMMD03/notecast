import json
from reportlab.platypus import Flowable

# EXTREMELY STRICT PROMPT INSTRUCTIONS FOR THE AI
DIAGRAM_INSTRUCTIONS = (
    "CRITICAL DIAGRAM INSTRUCTION: When creating architectural diagrams, pipelines, or flowcharts, "
    "you MUST output a strictly formatted JSON object wrapped exactly in a ```diagram code block. "
    "DO NOT output raw JSON. DO NOT use Mermaid for architectural diagrams. DO NOT invent your own keys. "
    "Use this EXACT format:\n"
    "```diagram\n"
    "{\n"
    "  \"title\": \"Your Diagram Title\",\n"
    "  \"direction\": \"TB\",\n"
    "  \"nodes\": [\n"
    "    {\"id\": \"1\", \"label\": \"Step 1\"},\n"
    "    {\"id\": \"2\", \"label\": \"Step 2\"}\n"
    "  ],\n"
    "  \"edges\": [\n"
    "    {\"from\": \"1\", \"to\": \"2\", \"label\": \"Action\"}\n"
    "  ]\n"
    "}\n"
    "```\n"
)

class NativeVectorDiagram(Flowable):
    """ReportLab Flowable that draws native vector diagrams on PDF directly."""
    def __init__(self, layout_data, max_width, max_height):
        Flowable.__init__(self)
        self.layout_data = layout_data
        self.width = max_width
        
        self.nodes = self.layout_data.get("nodes", [])
        self.box_w = 160
        self.box_h = 40
        self.spacing = 30
        
        self.height = len(self.nodes) * (self.box_h + self.spacing)
        if self.height > max_height:
            self.height = max_height

    def draw(self):
        if not self.nodes:
            self.canv.drawString(0, 0, "Empty Diagram")
            return
            
        center_x = self.width / 2.0
        current_y = self.height - self.box_h - 10
        
        title = self.layout_data.get("title", "")
        if title:
            self.canv.setFillColorRGB(0.2, 0.2, 0.2)
            self.canv.drawCentredString(center_x, self.height, title)
        
        for i, node in enumerate(self.nodes):
            # Box
            self.canv.setFillColorRGB(0.14, 0.39, 0.92) # Slate blue
            self.canv.roundRect(center_x - (self.box_w/2), current_y, self.box_w, self.box_h, 6, fill=1, stroke=0)
            
            # Text
            self.canv.setFillColorRGB(1, 1, 1)
            label = node.get("label", node.get("id", "Node"))
            self.canv.drawCentredString(center_x, current_y + 16, label)
            
            # Draw Line connecting to next node
            if i < len(self.nodes) - 1:
                self.canv.setStrokeColorRGB(0.6, 0.6, 0.6)
                self.canv.setLineWidth(2)
                
                start_y = current_y
                end_y = current_y - self.spacing
                
                self.canv.line(center_x, start_y, center_x, end_y)
                # Quick Arrow head
                self.canv.line(center_x, end_y, center_x - 4, end_y + 6)
                self.canv.line(center_x, end_y, center_x + 4, end_y + 6)
            
            current_y -= (self.box_h + self.spacing)

def pdf_flowable(layout_data, max_width=470.0, max_height=600.0):
    return NativeVectorDiagram(layout_data, max_width, max_height)

def pptx_fit(layout_data, max_w_in, max_h_in, cap_in=0.0):
    nodes = layout_data.get("nodes", [])
    box_height = 0.6
    spacing = 0.4
    needed_height = len(nodes) * (box_height + spacing) + cap_in
    return 1.0, max_w_in, needed_height

def add_diagram_to_slide(slide, layout_data, left_in, top_in, max_w_in, max_h_in):
    """Draws fully editable native shape flowcharts directly onto the PPTX slide."""
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    
    nodes = layout_data.get("nodes", [])
    if not nodes:
        return 0.5
        
    box_width = 2.5
    box_height = 0.6
    spacing = 0.4
    
    center_x = left_in + (max_w_in / 2.0)
    current_y = top_in
    
    title = layout_data.get("title", "")
    if title:
        tb = slide.shapes.add_textbox(Inches(left_in), Inches(current_y), Inches(max_w_in), Inches(0.4))
        p = tb.text_frame.paragraphs[0]
        p.text = title
        p.font.bold = True
        p.font.color.rgb = RGBColor(71, 85, 105)
        current_y += 0.5
    
    for i, node in enumerate(nodes):
        shape = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE, 
            Inches(center_x - (box_width/2)), 
            Inches(current_y), 
            Inches(box_width), 
            Inches(box_height)
        )
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor(37, 99, 235) 
        shape.line.fill.background()
        
        tf = shape.text_frame
        p = tf.paragraphs[0]
        p.text = node.get("label", node.get("id", ""))
        p.font.color.rgb = RGBColor(255, 255, 255)
        p.font.size = Pt(14)
        p.font.bold = True
        
        # Draw Down Arrow between shapes
        if i < len(nodes) - 1:
            arrow = slide.shapes.add_shape(
                MSO_SHAPE.DOWN_ARROW,
                Inches(center_x - 0.1),
                Inches(current_y + box_height + 0.05),
                Inches(0.2),
                Inches(spacing - 0.1)
            )
            arrow.fill.solid()
            arrow.fill.fore_color.rgb = RGBColor(148, 163, 184)
            arrow.line.fill.background()
        
        current_y += box_height + spacing
        
    return (current_y - top_in)
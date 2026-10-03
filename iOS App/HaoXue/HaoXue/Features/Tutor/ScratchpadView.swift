import PencilKit
import SwiftUI

private enum ScratchpadTool: String, CaseIterable {
    case pen, eraser

    var title: String { self == .pen ? "笔" : "橡皮" }
    var symbol: String { self == .pen ? "pencil.tip" : "eraser" }
}

struct ScratchpadView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Binding var drawing: PKDrawing
    @State private var tool: ScratchpadTool = .pen
    @State private var showingClearConfirmation = false
    @State private var isPresented = false

    var body: some View {
        NavigationStack {
            ScratchpadCanvas(drawing: $drawing, tool: $tool)
                .background(Color(uiColor: .systemBackground))
                // The scratchpad is a temporary thinking layer: it settles in
                // instead of hard-cutting over the lesson. Behaviour unchanged.
                .opacity(isPresented ? 1 : 0)
                .offset(y: isPresented || reduceMotion ? 0 : 20)
                .animation(DemoMotion.resolved(reduceMotion, DemoMotion.emphasized), value: isPresented)
                .onAppear {
                    withAnimation(DemoMotion.resolved(reduceMotion, DemoMotion.emphasized)) {
                        isPresented = true
                    }
                }
                .navigationTitle("草稿本")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarLeading) {
                        Button("清空", role: .destructive) { showingClearConfirmation = true }
                            .disabled(drawing.strokes.isEmpty)
                    }
                    ToolbarItem(placement: .topBarTrailing) {
                        Button("完成") { dismiss() }
                    }
                    ToolbarItemGroup(placement: .bottomBar) {
                        Spacer()
                        ForEach(ScratchpadTool.allCases, id: \.self) { candidate in
                            Button {
                                tool = candidate
                            } label: {
                                Image(systemName: candidate.symbol)
                                    .frame(width: 44, height: 36)
                                    .background(tool == candidate ? Color.blue.opacity(0.12) : .clear,
                                                in: RoundedRectangle(cornerRadius: 8))
                            }
                            .tint(tool == candidate ? .blue : .primary)
                            .accessibilityLabel(candidate.title)
                            .accessibilityAddTraits(tool == candidate ? .isSelected : [])
                        }
                        Spacer()
                    }
                }
                .alert("清空草稿？", isPresented: $showingClearConfirmation) {
                    Button("清空", role: .destructive) { drawing = PKDrawing() }
                    Button("取消", role: .cancel) { }
                } message: {
                    Text("当前草稿将被全部删除，此操作无法撤销。")
                }
        }
    }
}

private struct ScratchpadCanvas: UIViewRepresentable {
    @Binding var drawing: PKDrawing
    @Binding var tool: ScratchpadTool

    func makeUIView(context: Context) -> PKCanvasView {
        let canvas = PKCanvasView()
        canvas.accessibilityIdentifier = "scratchpadCanvas"
        canvas.drawingPolicy = .anyInput
        canvas.backgroundColor = .systemBackground
        canvas.drawing = drawing
        canvas.delegate = context.coordinator
        canvas.tool = PKInkingTool(.pen, color: .label, width: 3)
        let pencilInteraction = UIPencilInteraction()
        pencilInteraction.delegate = context.coordinator
        canvas.addInteraction(pencilInteraction)
        return canvas
    }

    func updateUIView(_ canvas: PKCanvasView, context: Context) {
        context.coordinator.parent = self
        if canvas.drawing.dataRepresentation() != drawing.dataRepresentation() {
            canvas.drawing = drawing
        }
        canvas.tool = tool == .pen
            ? PKInkingTool(.pen, color: .label, width: 3)
            : PKEraserTool(.vector)
    }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    final class Coordinator: NSObject, PKCanvasViewDelegate, UIPencilInteractionDelegate {
        var parent: ScratchpadCanvas

        init(_ parent: ScratchpadCanvas) { self.parent = parent }

        func canvasViewDrawingDidChange(_ canvasView: PKCanvasView) {
            parent.drawing = canvasView.drawing
        }

        func pencilInteraction(_ interaction: UIPencilInteraction,
                               didReceiveTap tap: UIPencilInteraction.Tap) {
            parent.tool = parent.tool == .pen ? .eraser : .pen
        }
    }
}

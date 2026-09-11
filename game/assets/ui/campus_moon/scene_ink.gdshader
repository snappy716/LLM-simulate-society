shader_type canvas_item;
render_mode unshaded;

// Bright opaque ink with a narrow silhouette edge, never a rectangular backplate.
uniform float emphasis : hint_range(0.0, 1.0) = 0.0;
varying vec4 vertex_tint;

void vertex() {
	vertex_tint = COLOR;
}

void fragment() {
	vec4 ink = texture(TEXTURE, UV);
	// About one display pixel at the 30 px glyph size (source canvas is 64 px).
	vec2 pixel = TEXTURE_PIXEL_SIZE * 2.0;
	float edge = 0.0;
	for (int x = -1; x <= 1; x++) {
		for (int y = -1; y <= 1; y++) {
			if (x != 0 || y != 0) {
				edge = max(edge, texture(TEXTURE, UV + vec2(float(x), float(y)) * pixel).a);
			}
		}
	}
	float light = dot(ink.rgb, vec3(0.2126, 0.7152, 0.0722));
	vec3 paper = mix(vec3(0.96, 0.985, 1.0), vec3(1.0), emphasis);
	vec3 blue = mix(vec3(0.28, 0.76, 1.0), vec3(0.58, 0.88, 1.0), emphasis);
	vec3 color = light > 0.65 ? paper : (light > 0.24 ? blue : vec3(0.10, 0.23, 0.31));
	float alpha = ink.a;
	float shadow_alpha = edge * (1.0 - alpha) * 0.85;
	float combined = alpha + shadow_alpha;
	vec3 composed = (color * alpha + vec3(0.07, 0.14, 0.19) * shadow_alpha) / max(combined, 0.001);
	COLOR = vec4(composed, combined) * vertex_tint;
}

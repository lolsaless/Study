import matplotlib.pyplot as plt

# 노드와 엣지를 정의합니다.
nodes = ['A', 'B', 'C', 'D']
edges = [('A', 'B'), ('B', 'C'), ('C', 'D')]

# 그래프를 생성합니다.
fig, ax = plt.subplots()
ax.set_xlim([0, 1])
ax.set_ylim([0, len(nodes)])
ax.axis('off')

# 노드를 그립니다.
node_y = 0
for node in nodes:
    ax.text(0.5, node_y, node, ha='center', va='center')
    node_y += 1

# 엣지를 그립니다.
for edge in edges:
    ax.annotate('', xy=(0.1, nodes.index(edge[0])), xytext=(0.4, nodes.index(edge[1])),
                arrowprops=dict(arrowstyle='->'))

# 다이어그램을 표시합니다.
plt.show()
